---
title: AI-Assisted UX Evaluation
emoji: 🔎
colorFrom: yellow
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# AI-Assisted UX Evaluation System

Structured heuristic UX evaluation of a web page using a staged, five-module
AI workflow (spec set in `../docs`, design decisions in
`../memory/ux-eval-system-knowledge.md`). Built with **FastAPI** + the
official **Anthropic SDK**. Human judgment stays central: weak evidence is
flagged for validation, never asserted.

## The pipeline (one POST /api/analyze)

1. **Evidence gathering** — fetch + clean the page HTML (SSRF-guarded), plus
   optional screenshots (vision), pasted content, and org/task context.
2. **Module 2 — Evidence Analysis**: all 8 dimensions, preliminary 1–10
   scores, strengths, concerns with observable evidence (no severity here).
3. **Module 3 — Finding Assessment**: independent severity + confidence
   (level + %) + user impact per finding.
4. **Module 4 — Recommendations**: one evidence-based rec per finding with
   effort (Low/Med/High) and priority (1–3); investigation recs for
   Validation-Needed findings.
5. **Module 5 — Report narrative** (prose only) + deterministic server-side
   assembly of the 10-section report — scores, roll-ups, and finding↔rec
   links are computed in code, never by the model.

Module 1 (methodology, scales, constraints) is the shared, prompt-cached
system prompt for every call. Temperature 0, structured output via tool-use.

## The framework

8 weighted dimensions (Navigation 20%, Visual Hierarchy 15%, Consistency 15%,
Feedback 10%, Error Prevention 10%, Accessibility 10%, Task Efficiency 10%,
Trust 10%) · scores 1–10 with bands · severity Critical/High/Medium/Low/
Validation Needed · confidence High (80–95%) / Medium (60–79%) / Low (30–59%).
No analytics, satisfaction, or WCAG-conformance claims — out-of-scope
conclusions are flagged for human validation. Without screenshots, purely
visual judgments are capped or flagged rather than asserted.

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
.venv/bin/python main.py           # http://localhost:8000
```

Tests (offline, no API key): `python -m pytest test_report.py -q`

## Config (env)

- `ANTHROPIC_API_KEY` (required) — server-side only
- `MODEL` (default `claude-haiku-4-5`)
- `RATE_LIMIT_SECONDS` (default 300 — one evaluation per visitor per 5 min)
- `ANALYSIS_ENABLED` (set `false` to pause the public demo without redeploy)
