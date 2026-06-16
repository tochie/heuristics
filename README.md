---
title: UX Review Assistant
emoji: 🔎
colorFrom: yellow
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# UX Review Assistant (demo)

A minimal web app: enter a website URL, and Claude (Sonnet 4) reviews it against
a fixed UX heuristic rubric — returning per-metric scores, confidence-rated
evidence, an overall weighted score, strengths, issues, and recommendations.

Built with **FastAPI** (async) + the official **Anthropic SDK**.

## What it scores

8 weighted heuristics (grounded in Nielsen's heuristics, Laws of UX, and WCAG):

| Metric | Weight |
|---|---|
| Navigation Clarity | 20% |
| Visual Hierarchy | 15% |
| Consistency & Standards | 15% |
| Feedback & System Visibility | 10% |
| Error Prevention & Recovery | 10% |
| Accessibility & Readability | 10% |
| Task Efficiency | 10% |
| Trust & Credibility | 10% |

Each finding carries a **Confidence** rating (High / Medium / Low) with evidence.
Confidence is metadata about the finding — it is **not** folded into the UX score.
The app deliberately avoids participant-only metrics (NPS, SUS, satisfaction).

## Setup

1. Create a virtual environment and install dependencies:

   ```bash
   cd /Volumes/T7/dev/ijeonu/anthropic
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Add your API key:

   ```bash
   cp .env.example .env
   # then edit .env and paste your ANTHROPIC_API_KEY
   ```

3. Run the server:

   ```bash
   uvicorn main:app --reload --port 8000
   # or: python3 main.py
   ```

4. Open http://localhost:8000 and paste a URL.

   Interactive API docs are auto-generated at http://localhost:8000/docs.

## How it works

```
browser ──POST /api/analyze {url}──> main.py (FastAPI)
                                       └─ analyzer.fetch_page()  (httpx fetches + cleans HTML)
                                       └─ analyzer.build_prompt() (rubric + cleaned HTML)
                                       └─ analyzer.call_claude()  (AsyncAnthropic SDK)
                                       └─ weighted overall computed server-side
browser <────────── analysis JSON ─────┘
```

The API key stays server-side and is never exposed to the browser. The page's
HTML is fetched server-side, scripts/styles stripped (structure + attributes
like `alt`, `aria-label`, `href` preserved), truncated, and sent to Claude.

## Files

- `main.py` — FastAPI app; serves the frontend and `/api/analyze`
- `analyzer.py` — async fetch, prompt, Claude call, parse, scoring
- `rubric.py` — the 8 metrics, weights, confidence rules, weighted-average math
- `static/` — the single-page frontend (`index.html`, `style.css`, `app.js`)
- `requirements.txt` — Python dependencies

## Notes / limits

- HTML-only review: it reasons from page source, so visual-only signals (true
  color contrast, rendered screenshots) are inferred, not measured — which is
  exactly why findings are confidence-tagged.
- JS-only single-page apps that render nothing in initial HTML will return thin
  results; the app warns when the page yields almost no readable HTML.
