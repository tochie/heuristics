"""
Core analysis logic: fetch a target page, build the prompt, call Claude,
and parse the structured result.

Async throughout. Uses httpx (async HTTP) to fetch the target page and the
official Anthropic SDK (AsyncAnthropic) to call Claude.
"""

import json
import re
from html.parser import HTMLParser

import httpx
from anthropic import AsyncAnthropic

from rubric import METRICS, CONFIDENCE_RULES, weighted_overall

# Default model. Override with the MODEL env var if needed.
DEFAULT_MODEL = "claude-haiku-4-5"

# Keep the prompt within sane token bounds for a demo.
MAX_HTML_CHARS = 120_000

FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}


class _Stripper(HTMLParser):
    """Drops <script>/<style> bodies but keeps tags + attributes so Claude
    can still reason about structure (nav, headings, alt text, aria, forms)."""

    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        attr_str = "".join(
            f' {k}="{v}"' for k, v in attrs
            if k in ("href", "alt", "aria-label", "role", "type", "name",
                     "placeholder", "id", "class", "title", "lang")
        )
        self.parts.append(f"<{tag}{attr_str}>")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text)

    def result(self):
        cleaned = " ".join(self.parts)
        return re.sub(r"\s+", " ", cleaned).strip()


def normalize_url(url):
    url = (url or "").strip()
    if not url:
        raise ValueError("No URL provided.")
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    return url


async def fetch_page(url):
    """Return cleaned, structure-preserving HTML for the page, plus the title."""
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=20, headers=FETCH_HEADERS
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise ValueError(f"Could not fetch page (HTTP {e.response.status_code}).")
    except httpx.RequestError as e:
        raise ValueError(f"Could not reach the site ({e}).")

    html = resp.text  # httpx decodes using the response charset

    title_match = re.search(r"<title[^>]*>(.*?)</title>", html,
                            re.IGNORECASE | re.DOTALL)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""

    stripper = _Stripper()
    try:
        stripper.feed(html)
    except Exception:
        pass
    cleaned = stripper.result()
    if len(cleaned) > MAX_HTML_CHARS:
        cleaned = cleaned[:MAX_HTML_CHARS] + " …[truncated]"
    return cleaned, title


def _metric_block():
    lines = []
    for m in METRICS:
        looks = "; ".join(m["looks_for"])
        lines.append(f'- {m["label"]} (key: "{m["key"]}", weight {m["weight"]}%) '
                     f"— look for: {looks}")
    return "\n".join(lines)


def build_prompt(url, title, cleaned_html):
    keys = ", ".join(f'"{m["key"]}"' for m in METRICS)
    return f"""You are a UX Research-minded review assistant. Analyze the website below \
against a fixed heuristic rubric grounded in Nielsen's heuristics, Laws of UX, and WCAG.

You are given the page's cleaned HTML (scripts/styles removed, structure and \
attributes preserved). Reason ONLY from observable evidence in this source. \
Do NOT measure satisfaction, NPS, SUS, memorability, or anything needing real \
participants — score only what the page evidence supports.

URL: {url}
Page title: {title or "(none found)"}

SCORE THESE 8 METRICS (each 0-10 integer):
{_metric_block()}

CONFIDENCE — metadata about each finding, NEVER folded into the UX score:
{CONFIDENCE_RULES}

For every metric provide:
- "score": integer 0-10
- "finding": one or two sentences, specific to THIS page
- "confidence": "High" | "Medium" | "Low"
- "confidence_reason": why that tier (tie it to the evidence vs. inference distinction)
- "evidence": array of 1-4 short concrete observations from the source

Also provide:
- "strengths": array of 2-5 short UX strengths
- "issues": array of 2-5 short UX issues
- "recommendations": array of 3-6 specific, actionable recommendations
- "summary": 1-2 sentence overall impression

Respond with ONLY a single valid JSON object, no markdown fences, in exactly this shape:
{{
  "metrics": {{
     <one entry per metric key: {keys}>,
     "<key>": {{"score": 0, "finding": "", "confidence": "", "confidence_reason": "", "evidence": []}}
  }},
  "strengths": [],
  "issues": [],
  "recommendations": [],
  "summary": ""
}}

PAGE SOURCE (cleaned):
{cleaned_html}
"""


def _extract_json(text):
    """Claude should return raw JSON, but tolerate fences / surrounding prose."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("Model did not return parseable JSON.")


async def call_claude(client, model, prompt):
    """Call the Anthropic Messages API via the async SDK and return the text."""
    try:
        msg = await client.messages.create(
            model=model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        raise ValueError(f"Anthropic API error: {e}")

    text = "".join(block.text for block in msg.content
                   if getattr(block, "type", None) == "text")
    if not text:
        raise ValueError("Empty response from model.")
    return text


async def analyze(client, model, url):
    """Full pipeline. Returns the result dict the frontend renders.

    `client` is an AsyncAnthropic instance (created once and reused)."""
    url = normalize_url(url)
    cleaned_html, title = await fetch_page(url)
    if len(cleaned_html) < 40:
        raise ValueError("The page returned almost no readable HTML "
                         "(it may be a JS-only app or blocked the request).")

    prompt = build_prompt(url, title, cleaned_html)
    raw = await call_claude(client, model, prompt)
    parsed = _extract_json(raw)

    # Compute the weighted overall ourselves — don't trust the model's math.
    scores = {}
    metrics_out = parsed.get("metrics", {})
    for m in METRICS:
        entry = metrics_out.get(m["key"]) or {}
        try:
            s = int(round(float(entry.get("score"))))
        except (TypeError, ValueError):
            s = None
        if s is not None:
            s = max(0, min(10, s))
            scores[m["key"]] = s
        # attach rubric metadata for the frontend
        entry["label"] = m["label"]
        entry["weight"] = m["weight"]
        entry["score"] = s
        metrics_out[m["key"]] = entry

    overall = weighted_overall(scores)

    return {
        "url": url,
        "title": title,
        "model": model,
        "overall_score": overall,
        "metrics": metrics_out,
        "metric_order": [m["key"] for m in METRICS],
        "strengths": parsed.get("strengths", []),
        "issues": parsed.get("issues", []),
        "recommendations": parsed.get("recommendations", []),
        "summary": parsed.get("summary", ""),
    }
