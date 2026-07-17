"""
Ismara — FastAPI backend
Looks up a name, does fuzzy matching if exact match not found,
and generates a shareable card image (PNG) with the result.
"""
import json
import os
import difflib
import textwrap
from pathlib import Path
from io import BytesIO

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

BASE_DIR = Path(__file__).parent
PROJECT_ROOT = BASE_DIR.parent
DATA_PATH = PROJECT_ROOT / "data" / "names_master.json"
FONTS_DIR = BASE_DIR / "assets" / "fonts"

app = FastAPI(title="Ismara API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Load dataset once at startup ----------
# Single pre-deduplicated master file. Deduplication and tier-priority merging
# (premium citations > standard entries) was done once during data preparation,
# so this is a straight load — no runtime merge/dedup needed.
with open(DATA_PATH, "r", encoding="utf-8") as f:
    NAMES_DB: list[dict] = json.load(f)

# Build a lowercase lookup index for fast exact matches
NAME_INDEX = {entry["name"].lower(): entry for entry in NAMES_DB}
ALL_NAME_KEYS = list(NAME_INDEX.keys())


class NameResult(BaseModel):
    query: str
    matched: bool
    suggestion: str | None = None
    tier: str | None = None
    name: str | None = None
    arabic: str | None = None
    origin: str | None = None
    meaning: str | None = None
    notable_figure: str | None = None
    reference: str | None = None
    reference_type: str | None = None
    fun_fact: str | None = None


def lookup_name(query: str) -> dict:
    """Exact match first, then fuzzy match fallback."""
    q = query.strip().lower()
    if not q:
        raise HTTPException(status_code=400, detail="Name cannot be empty.")

    if q in NAME_INDEX:
        return {"matched": True, "entry": NAME_INDEX[q], "suggestion": None}

    # Fuzzy match: find closest name in dataset
    close = difflib.get_close_matches(q, ALL_NAME_KEYS, n=1, cutoff=0.6)
    if close:
        return {"matched": False, "entry": NAME_INDEX[close[0]], "suggestion": close[0]}

    return {"matched": False, "entry": None, "suggestion": None}


@app.get("/api/health")
def health():
    return {"status": "ok", "names_loaded": len(NAMES_DB)}


@app.get("/api/lookup", response_model=NameResult)
def lookup(name: str):
    result = lookup_name(name)
    if result["entry"] is None:
        return NameResult(query=name, matched=False, suggestion=None)

    entry = result["entry"]
    return NameResult(
        query=name,
        matched=result["matched"],
        suggestion=result["suggestion"],
        tier=entry.get("tier", "premium"),
        name=entry["name"],
        arabic=entry.get("arabic"),
        origin=entry.get("origin"),
        meaning=entry.get("meaning"),
        notable_figure=entry.get("notable_figure"),
        reference=entry.get("reference"),
        reference_type=entry.get("reference_type"),
        fun_fact=entry.get("fun_fact"),
    )


@app.get("/api/names")
def list_names():
    """Returns all available names — useful for autocomplete on frontend."""
    return {"names": [e["name"] for e in NAMES_DB]}


@app.get("/api/suggest")
def suggest(q: str, limit: int = 8):
    """Lightweight prefix + substring suggestions for autocomplete-as-you-type."""
    q = q.strip().lower()
    if not q:
        return {"suggestions": []}

    starts = []
    contains = []
    for key, entry in NAME_INDEX.items():
        if key.startswith(q):
            starts.append(entry["name"])
        elif q in key:
            contains.append(entry["name"])
        if len(starts) >= limit:
            break

    results = (starts + contains)[:limit]
    return {"suggestions": results}


# ---------- Card image generation ----------

def _load_font(size: int, bold: bool = False):
    """Try to load a nice font, fall back to default if unavailable."""
    candidates = [
        FONTS_DIR / ("Poppins-Bold.ttf" if bold else "Poppins-Regular.ttf"),
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(str(c), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _load_arabic_font(size: int):
    """Load a font that actually supports Arabic glyph joining/shaping."""
    candidates = [
        FONTS_DIR / "NotoNaskhArabic-Bold.ttf",
        "/System/Library/Fonts/SFArabic.ttf",
        "/System/Library/Fonts/Supplemental/Damascus.ttc",
        "/System/Library/Fonts/GeezaPro.ttc",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(str(c), size)
        except Exception:
            continue
    return ImageFont.load_default()


def shape_arabic(text: str) -> str:
    """Reshape Arabic text into joined glyph forms and reorder for RTL display."""
    if not text:
        return text
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)


def _draw_diamond(draw, cx, cy, size, fill):
    draw.polygon([(cx, cy - size), (cx + size, cy), (cx, cy + size), (cx - size, cy)], fill=fill)


# ---------- Theme palettes ----------
# Single source of truth for colors — used both for card generation (RGB tuples)
# and exposed via /api/themes (as hex) so the frontend selector always matches.
THEMES = {
    "turquoise": {
        "label": "Turquoise Dream",
        "bg_top": (10, 58, 68), "bg_mid": (13, 90, 100), "bg_bottom": (6, 28, 34),
        "gold": (94, 224, 210), "rose": (56, 178, 200), "cream": (240, 253, 250),
    },
    "ocean": {
        "label": "Ocean Breeze",
        "bg_top": (8, 42, 74), "bg_mid": (12, 74, 110), "bg_bottom": (5, 20, 38),
        "gold": (120, 216, 232), "rose": (72, 150, 220), "cream": (240, 250, 255),
    },
    "sapphire": {
        "label": "Sapphire Night",
        "bg_top": (10, 22, 62), "bg_mid": (16, 40, 96), "bg_bottom": (5, 10, 30),
        "gold": (168, 200, 255), "rose": (90, 140, 235), "cream": (245, 248, 255),
    },
    "indigo": {
        "label": "Royal Indigo",
        "bg_top": (33, 18, 58), "bg_mid": (58, 22, 46), "bg_bottom": (12, 8, 20),
        "gold": (232, 189, 84), "rose": (214, 92, 108), "cream": (250, 245, 232),
    },
    "amethyst": {
        "label": "Amethyst Bloom",
        "bg_top": (44, 20, 66), "bg_mid": (76, 30, 96), "bg_bottom": (18, 8, 28),
        "gold": (230, 190, 250), "rose": (188, 110, 220), "cream": (250, 245, 255),
    },
    "plum": {
        "label": "Plum Velvet",
        "bg_top": (48, 16, 40), "bg_mid": (72, 20, 54), "bg_bottom": (16, 6, 14),
        "gold": (240, 190, 200), "rose": (216, 100, 140), "cream": (255, 244, 248),
    },
    "crimson": {
        "label": "Crimson Noor",
        "bg_top": (52, 12, 20), "bg_mid": (84, 18, 28), "bg_bottom": (18, 5, 8),
        "gold": (240, 200, 120), "rose": (230, 90, 90), "cream": (255, 246, 238),
    },
    "sunset": {
        "label": "Sunset Rose",
        "bg_top": (58, 22, 40), "bg_mid": (94, 36, 34), "bg_bottom": (20, 8, 14),
        "gold": (250, 200, 120), "rose": (240, 120, 100), "cream": (255, 246, 236),
    },
    "amber": {
        "label": "Desert Amber",
        "bg_top": (54, 34, 12), "bg_mid": (84, 52, 16), "bg_bottom": (20, 12, 4),
        "gold": (255, 214, 130), "rose": (230, 150, 70), "cream": (255, 248, 234),
    },
    "emerald": {
        "label": "Emerald Classic",
        "bg_top": (14, 74, 66), "bg_mid": (10, 58, 52), "bg_bottom": (8, 33, 30),
        "gold": (212, 175, 55), "rose": (150, 200, 120), "cream": (250, 245, 232),
    },
    "mint": {
        "label": "Mint Frost",
        "bg_top": (10, 58, 50), "bg_mid": (18, 88, 78), "bg_bottom": (5, 26, 22),
        "gold": (170, 240, 210), "rose": (100, 210, 180), "cream": (245, 255, 250),
    },
    "midnight": {
        "label": "Midnight Gold",
        "bg_top": (14, 14, 22), "bg_mid": (26, 24, 38), "bg_bottom": (4, 4, 8),
        "gold": (232, 189, 84), "rose": (140, 140, 180), "cream": (250, 248, 240),
    },
}
DEFAULT_THEME = "turquoise"


def _rgb_to_hex(rgb):
    return "#%02x%02x%02x" % rgb


def generate_card_image(entry: dict, theme_key: str = DEFAULT_THEME) -> Image.Image:
    theme = THEMES.get(theme_key, THEMES[DEFAULT_THEME])
    W, H = 1080, 1350  # portrait, Instagram-story-friendly-ish (4:5)
    bg_top = theme["bg_top"]
    bg_mid = theme["bg_mid"]
    bg_bottom = theme["bg_bottom"]
    gold = theme["gold"]
    gold_soft = tuple(min(255, c + 30) for c in gold)
    rose = theme["rose"]
    cream = theme["cream"]

    img = Image.new("RGB", (W, H), bg_top)
    draw = ImageDraw.Draw(img)

    # Vertical 3-stop gradient background (indigo -> maroon -> near-black)
    for y in range(H):
        t = y / H
        if t < 0.5:
            lt = t / 0.5
            r = int(bg_top[0] + (bg_mid[0] - bg_top[0]) * lt)
            g = int(bg_top[1] + (bg_mid[1] - bg_top[1]) * lt)
            b = int(bg_top[2] + (bg_mid[2] - bg_top[2]) * lt)
        else:
            lt = (t - 0.5) / 0.5
            r = int(bg_mid[0] + (bg_bottom[0] - bg_mid[0]) * lt)
            g = int(bg_mid[1] + (bg_bottom[1] - bg_mid[1]) * lt)
            b = int(bg_mid[2] + (bg_bottom[2] - bg_mid[2]) * lt)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Soft radial glow behind the top section (halo effect for Arabic name)
    glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    glow_cx, glow_cy, glow_r = W // 2, 290, 340
    for i in range(glow_r, 0, -4):
        alpha = int(40 * (1 - i / glow_r))
        glow_draw.ellipse(
            [glow_cx - i, glow_cy - i * 0.6, glow_cx + i, glow_cy + i * 0.6],
            fill=(gold[0], gold[1], gold[2], alpha)
        )
    img.paste(Image.alpha_composite(img.convert("RGBA"), glow_layer).convert("RGB"), (0, 0))
    draw = ImageDraw.Draw(img)

    # Decorative border (double frame, Mughal-inspired)
    margin = 36
    draw.rectangle([margin, margin, W - margin, H - margin], outline=gold, width=3)
    margin2 = margin + 14
    draw.rectangle([margin2, margin2, W - margin2, H - margin2], outline=rose, width=1)

    # Corner flourish accents
    corner_len = 34
    for (x0, y0, dx, dy) in [
        (margin2, margin2, 1, 1),
        (W - margin2, margin2, -1, 1),
        (margin2, H - margin2, 1, -1),
        (W - margin2, H - margin2, -1, -1),
    ]:
        draw.line([(x0, y0), (x0 + dx * corner_len, y0)], fill=gold, width=3)
        draw.line([(x0, y0), (x0, y0 + dy * corner_len)], fill=gold, width=3)
        _draw_diamond(draw, x0 + dx * (corner_len + 16), y0 + dy * (corner_len + 16), 6, gold)

    # Small decorative diamond row along the top edge, inside the frame
    for i in range(-3, 4):
        _draw_diamond(draw, W // 2 + i * 40, margin2 + 6, 4, rose if i % 2 == 0 else gold)

    # Fonts
    f_brand = _load_font(30, bold=True)
    f_arabic = _load_arabic_font(90)
    f_arabic_body = _load_arabic_font(34)
    f_name = _load_font(64, bold=True)
    f_label = _load_font(24, bold=True)
    f_meaning = _load_font(34)
    f_body = _load_font(28)
    f_footer = _load_font(22)

    cx = W // 2
    is_premium = entry.get("tier", "premium") == "premium"

    # Brand header with crescent flourish
    draw.arc([cx - 190, 92, cx - 150, 132], start=30, end=330, fill=gold, width=3)
    draw.text((cx, 110), "ISMARA", font=f_brand, fill=gold, anchor="mm")
    _draw_diamond(draw, cx + 165, 110, 7, rose)

    # Arabic name (large) — only if we have a script rendering
    arabic_text = entry.get("arabic")
    y_cursor = 230
    if arabic_text:
        draw.text((cx, y_cursor), shape_arabic(arabic_text), font=f_arabic, fill=cream, anchor="mm")
        y_cursor = 340
    else:
        y_cursor = 280

    # English name
    draw.text((cx, y_cursor), entry["name"].upper(), font=f_name, fill=gold, anchor="mm")
    y_cursor += 60

    # Origin tag (shown for standard-tier / always if present)
    if entry.get("origin"):
        draw.text((cx, y_cursor), f"{entry['origin']} origin", font=f_footer, fill=rose, anchor="mm")
        y_cursor += 34

    # Divider with diamond accent
    draw.line([(cx - 130, y_cursor), (cx - 20, y_cursor)], fill=gold, width=2)
    _draw_diamond(draw, cx, y_cursor, 8, rose)
    draw.line([(cx + 20, y_cursor), (cx + 130, y_cursor)], fill=gold, width=2)
    y = y_cursor + 50

    # Meaning
    draw.text((cx, y), "MEANING", font=f_label, fill=gold, anchor="mm")
    y += 45
    meaning_text = entry["meaning"]
    if entry.get("meaning_lang") == "ar":
        # Arabic-script meaning: reshape + reorder for correct RTL display
        wrapped_meaning = textwrap.wrap(meaning_text, width=28)
        wrapped_meaning = [shape_arabic(line) for line in wrapped_meaning]
        meaning_font = f_arabic_body
    else:
        wrapped_meaning = textwrap.wrap(meaning_text, width=34)
        meaning_font = f_meaning
    for line in wrapped_meaning:
        draw.text((cx, y), line, font=meaning_font, fill=cream, anchor="mm")
        y += 46

    if is_premium and entry.get("notable_figure"):
        # Notable figure
        y += 40
        draw.text((cx, y), "NOTABLE FIGURE", font=f_label, fill=gold, anchor="mm")
        y += 42
        wrapped_figure = textwrap.wrap(entry["notable_figure"], width=38)
        for line in wrapped_figure:
            draw.text((cx, y), line, font=f_body, fill=cream, anchor="mm")
            y += 38

        # Reference quote box
        y += 45
        ref_box_top = y
        wrapped_ref = textwrap.wrap(entry["reference"], width=42)
        ref_lines = len(wrapped_ref)
        ref_box_height = 60 + ref_lines * 36
        draw.rounded_rectangle(
            [90, ref_box_top, W - 90, ref_box_top + ref_box_height],
            radius=18, outline=gold, width=2
        )
        ry = ref_box_top + 30
        draw.text((cx, ry), f"— {entry['reference_type']} —", font=f_label, fill=gold, anchor="mm")
        ry += 40
        for line in wrapped_ref:
            draw.text((cx, ry), line, font=f_body, fill=cream, anchor="mm")
            ry += 36

        # Fun fact footer
        fy = ref_box_top + ref_box_height + 50
        draw.text((cx, fy), "DID YOU KNOW?", font=f_label, fill=gold, anchor="mm")
        fy += 38
        wrapped_fact = textwrap.wrap(entry["fun_fact"], width=44)
        for line in wrapped_fact:
            draw.text((cx, fy), line, font=f_body, fill=cream, anchor="mm")
            fy += 34
    else:
        # Standard tier: simple, honest card — no fabricated religious claims
        y += 60
        draw.text((cx, y), "🌙", font=_load_font(48), fill=gold, anchor="mm")
        y += 70
        note = "A beautiful name from a rich global tradition."
        for line in textwrap.wrap(note, width=40):
            draw.text((cx, y), line, font=f_body, fill=cream, anchor="mm")
            y += 34

    # Footer branding
    draw.text((cx, H - 70), "Generated by Ismara", font=f_footer, fill=gold, anchor="mm")

    return img


@app.get("/api/themes")
def list_themes():
    """Returns all available card themes for the frontend theme selector."""
    return {
        "default": DEFAULT_THEME,
        "themes": [
            {
                "key": key,
                "label": t["label"],
                "colors": {
                    "bgTop": _rgb_to_hex(t["bg_top"]),
                    "bgMid": _rgb_to_hex(t["bg_mid"]),
                    "bgBottom": _rgb_to_hex(t["bg_bottom"]),
                    "gold": _rgb_to_hex(t["gold"]),
                    "rose": _rgb_to_hex(t["rose"]),
                    "cream": _rgb_to_hex(t["cream"]),
                }
            }
            for key, t in THEMES.items()
        ]
    }


@app.get("/api/card")
def get_card(name: str, theme: str = DEFAULT_THEME):
    result = lookup_name(name)
    entry = result["entry"]
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No name found matching '{name}'.")

    if theme not in THEMES:
        theme = DEFAULT_THEME

    img = generate_card_image(entry, theme_key=theme)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png", headers={
        "Content-Disposition": f'inline; filename="{entry["name"]}_ismara_card.png"'
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
