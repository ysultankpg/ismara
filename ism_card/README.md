# Ismara 🌙

Discover the meaning, Quranic/Hadith reference, and notable Islamic figure behind
any name — then get a beautiful, shareable card image.

## Project structure

```
ism_card/
├── backend/
│   ├── main.py            # FastAPI app: lookup + card image generation
│   └── requirements.txt
├── data/
│   └── names.json         # Curated name dataset (39 names to start)
└── frontend/
    └── index.html         # Single-page UI (no build step needed)
```

## Running it

### 1. Backend

```bash
cd ism_card/backend
python3 -m venv venv
source venv/bin/activate       # on Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

This starts the API at `http://localhost:8000`.

Quick check:
- `GET /api/health` → confirms it's running + how many names are loaded
- `GET /api/lookup?name=Yusuf` → returns structured meaning data
- `GET /api/card?name=Yusuf` → returns a PNG card image directly

### 2. Frontend

Just open `ism_card/frontend/index.html` in your browser (double-click it, or
serve it with any static server). It talks to `http://localhost:8000` by default —
change `API_BASE` in the `<script>` tag if you deploy the backend elsewhere.

## How it works

1. User types a name → frontend calls `/api/lookup`
2. Backend does **exact match** first (fast dict lookup), then falls back to
   **fuzzy matching** (`difflib`) for typos/variants (e.g. "Yousuf" → "Yusuf")
3. If a match is found, frontend requests `/api/card`, which renders a
   PNG card server-side using Pillow (gradient background, Arabic calligraphy,
   meaning, notable figure, Quran/Hadith reference, fun fact)
4. User can **Download** or **Share** (via Web Share API) the card image

## Extending the dataset

`data/names.json` currently has 39 names. To grow it:
- Add entries following the same schema (`name`, `arabic`, `gender`, `meaning`,
  `notable_figure`, `reference`, `reference_type`, `fun_fact`)
- No code changes needed — the backend reloads the whole file on startup
- Good next step: scrape/curate ~500 common Muslim names from authenticated
  sources (e.g. Islamic name meaning references, checked against Quran/Hadith)

## Roadmap ideas (Phase 2+)

- [ ] Add a `/api/names` powered autocomplete on the frontend as you type
- [ ] Support Arabic-script input (right now lookup is by English transliteration)
- [ ] Add multiple card design themes (user picks a color palette before generating)
- [ ] Deploy backend (Render/Railway/Fly.io) + frontend (Vercel/Netlify) for public link
- [ ] Analytics: track which names are searched most (helps prioritize dataset growth)
- [ ] "Baby Name Finder" mode: filter by meaning/gender for parents naming a child
- [ ] Bridge into Sunnah Habit Tracker: "Your name means Patience — build the Sabr habit"
