"""
Evaluation pipeline — orchestrates the module calls (Doc 3 §5 / Doc 2):

  evidence gathering -> M2 evidence analysis -> M3 finding assessment
  -> M4 recommendations -> deterministic assembly -> M5 narrative -> report

Design decisions (see ../memory/ux-eval-system-knowledge.md):
- Module 1 is the shared, prompt-cached system prompt (no handshake call).
- Four API calls total, single-turn each, structured output via tool-use,
  temperature 0.
- Screenshots go only to Module 2 (the evidence stage).
- All arithmetic and joining happens server-side in report.py.
"""

import prompts
import schemas
from fetcher import fetch_page, normalize_url
from report import (
    assemble_report, build_digest, build_findings, build_recommendations,
)
from rubric import DIMENSION_BY_KEY, DIMENSION_KEYS, overall_score, score_band

MAX_MODULE_TOKENS = 8192
MAX_FINDINGS = 40          # hard cap so a pathological page can't run away


class EvaluationError(ValueError):
    """User-visible pipeline failure."""


async def _call_module(client, model, system_prompt, user_content, tool):
    """One structured-output call. Returns the tool input dict.

    A response cut off by max_tokens yields a truncated (often empty) tool
    input — that must fail loudly, not degrade into an empty-looking result
    (it silently produced an all-'insufficient evidence' report once)."""
    msg = await client.messages.create(
        model=model,
        max_tokens=MAX_MODULE_TOKENS,
        temperature=0,
        system=[{
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_content}],
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
    )
    if msg.stop_reason == "max_tokens":
        raise EvaluationError(
            "The evaluation output was cut off mid-generation. Please retry; "
            "if it persists, evaluate a smaller page or fewer screenshots.")
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use":
            return block.input
    raise EvaluationError("The model returned no structured output.")


def _gather_evidence_text(inputs, cleaned_html, title):
    parts = []
    if inputs.get("url"):
        parts.append(f"URL: {inputs['url']}")
        parts.append(f"Page title: {title or '(none found)'}")
    if cleaned_html:
        parts.append(f"PAGE SOURCE (cleaned, scripts/styles removed):\n{cleaned_html}")
    if inputs.get("page_content"):
        parts.append(f"PAGE CONTENT (supplied by the user):\n{inputs['page_content'][:20000]}")
    ctx = []
    if inputs.get("organization_description"):
        ctx.append(f"Organization description: {inputs['organization_description'][:2000]}")
    if inputs.get("primary_user_tasks"):
        ctx.append(f"Primary user tasks: {inputs['primary_user_tasks'][:2000]}")
    if inputs.get("known_concerns"):
        ctx.append(f"Known concerns: {inputs['known_concerns'][:2000]}")
    if ctx:
        parts.append(
            "CONTEXT (for understanding intended purpose ONLY — do not assume "
            "users complete these tasks successfully unless the evidence shows "
            "it):\n" + "\n".join(ctx))
    return "\n\n".join(parts)


def _validate_m2(m2):
    """Normalize Module 2 output: all 8 dimensions exactly once, unique
    sequential finding ids, finding-count cap."""
    by_key = {}
    for dim in m2.get("dimensions", []):
        if dim.get("key") in DIMENSION_KEYS and dim["key"] not in by_key:
            by_key[dim["key"]] = dim
    missing = [k for k in DIMENSION_KEYS if k not in by_key]
    for k in missing:
        by_key[k] = {"key": k, "preliminary_score": None,
                     "insufficient_evidence": True, "strengths": [],
                     "concerns": []}
    m2["dimensions"] = [by_key[k] for k in DIMENSION_KEYS]

    # Re-issue ids sequentially (dedupes and normalizes model numbering).
    n = 0
    for dim in m2["dimensions"]:
        kept = []
        for concern in dim.get("concerns", []):
            if n >= MAX_FINDINGS:
                break
            n += 1
            concern["id"] = f"F{n}"
            concern.setdefault("validation_needed", False)
            concern["concern"] = str(concern.get("concern", "")).strip()
            concern["supporting_evidence"] = str(
                concern.get("supporting_evidence", "")).strip()
            if concern["concern"] and concern["supporting_evidence"]:
                kept.append(concern)
            else:
                n -= 1
        dim["concerns"] = kept
        score = dim.get("preliminary_score")
        if score is not None:
            dim["preliminary_score"] = max(1, min(10, int(score)))
        if dim.get("insufficient_evidence"):
            dim["preliminary_score"] = None
    return m2


def _findings_index(m2):
    return [
        {"finding_id": c["id"], "dimension": d["key"],
         "concern": c["concern"], "supporting_evidence": c["supporting_evidence"],
         "validation_needed": c["validation_needed"]}
        for d in m2["dimensions"] for c in d["concerns"]
    ]


async def run_evaluation(client, model, inputs):
    """Full pipeline. `inputs` keys: url?, page_content?, screenshots?
    (list of {media_type, data} base64), organization_description?,
    primary_user_tasks?, known_concerns?. Returns the report dict."""
    url = inputs.get("url")
    cleaned_html, title = "", ""
    if url:
        url = normalize_url(url)
        inputs["url"] = url
        cleaned_html, title = await fetch_page(url)
        if len(cleaned_html) < 40 and not inputs.get("screenshots") \
                and not inputs.get("page_content"):
            raise EvaluationError(
                "The page returned almost no readable HTML (it may be a "
                "JS-only app or blocked the request). Supply screenshots or "
                "page content instead.")

    screenshots = inputs.get("screenshots") or []
    has_screenshots = len(screenshots) > 0
    evidence_text = _gather_evidence_text(inputs, cleaned_html, title)
    if not evidence_text.strip() and not has_screenshots:
        raise EvaluationError(
            "An evaluation cannot be performed: no observable webpage "
            "evidence was supplied. Provide a public URL, screenshots, or "
            "page content.")

    evidence_supplied = [s for s, ok in (
        ("Website URL", bool(url)),
        ("Page source (fetched)", bool(cleaned_html)),
        (f"Screenshots ({len(screenshots)})", has_screenshots),
        ("Page content (supplied)", bool(inputs.get("page_content"))),
        ("Organization description", bool(inputs.get("organization_description"))),
        ("Primary user tasks", bool(inputs.get("primary_user_tasks"))),
        ("Known concerns", bool(inputs.get("known_concerns"))),
    ) if ok]

    # ---- Module 2: evidence analysis (screenshots attach here only) ----
    m2_content = [
        *({"type": "image",
           "source": {"type": "base64",
                      "media_type": s["media_type"],
                      "data": s["data"]}} for s in screenshots),
        {"type": "text",
         "text": prompts.m2_evidence_prompt(evidence_text, has_screenshots)},
    ]
    m2 = await _call_module(client, model, prompts.SYSTEM_PROMPT,
                            m2_content, schemas.M2_EVIDENCE_ANALYSIS)
    if not m2.get("dimensions"):
        raise EvaluationError(
            "The evidence analysis returned no dimensions (malformed model "
            "output). Please retry.")
    m2 = _validate_m2(m2)
    findings_index = _findings_index(m2)

    # ---- Module 3: severity + confidence ----
    if findings_index:
        m3 = await _call_module(
            client, model, prompts.SYSTEM_PROMPT,
            [{"type": "text", "text": prompts.m3_assessment_prompt(
                {"dimensions": m2["dimensions"]})}],
            schemas.M3_FINDING_ASSESSMENT)
    else:
        m3 = {"assessments": []}
    findings = build_findings(m2, m3)

    # ---- Module 4: recommendations ----
    if findings:
        m4 = await _call_module(
            client, model, prompts.SYSTEM_PROMPT,
            [{"type": "text", "text": prompts.m4_recommendation_prompt(
                m3, findings_index)}],
            schemas.M4_RECOMMENDATIONS)
    else:
        m4 = {"recommendations": []}
    recommendations = build_recommendations(findings, m4)

    # ---- deterministic roll-ups + Module 5 narrative ----
    inputs_meta = {
        "url": url, "title": title,
        "evidence_supplied": evidence_supplied,
        "has_screenshots": has_screenshots,
        "positive_observations": m2.get("positive_observations", []),
    }
    scores = {d["key"]: d["preliminary_score"] for d in m2["dimensions"]}
    score, band = overall_score(scores)
    dim_rows_stub = [
        {"label": DIMENSION_BY_KEY[d["key"]]["label"],
         "score": d["preliminary_score"],
         "band": score_band(d["preliminary_score"]),
         "strengths": d.get("strengths", []),
         "concern_count": len(d.get("concerns", []))}
        for d in m2["dimensions"]
    ]
    digest = build_digest(inputs_meta, dim_rows_stub, findings,
                          recommendations, score, band)
    narrative = await _call_module(
        client, model, prompts.SYSTEM_PROMPT,
        [{"type": "text", "text": prompts.m5_narrative_prompt(digest)}],
        schemas.M5_REPORT_NARRATIVE)

    return assemble_report(inputs_meta, m2, findings, recommendations,
                           narrative, model)
