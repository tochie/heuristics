"""
Prompt library — faithful implementation of Doc 2 ("AI Evaluation Prompt
Library") with the resolutions from ../memory/ux-eval-system-knowledge.md.

Module 1 is NOT a separate API call (the doc's "acknowledge and wait"
handshake wastes a round-trip): it is the shared system prompt for every
module call, so the methodology, scales, and constraints are identically
in force at each stage — and it is prompt-cacheable.
"""

import json

from rubric import (
    CONFIDENCE_BANDS, CONFIDENCE_DEFINITIONS, DIMENSIONS,
    SEVERITY_DEFINITIONS, SCORE_BANDS,
)


def _dimension_table():
    lines = []
    for d in DIMENSIONS:
        crit = "; ".join(d["criteria"])
        lines.append(f'- {d["label"]} (key "{d["key"]}", weight {d["weight"]}%): {crit}')
    return "\n".join(lines)


def _score_scale():
    return "\n".join(f"  {lo}-{hi}  {label}" for lo, hi, label in SCORE_BANDS)


def _severity_block():
    return "\n".join(f"  {k}: {v}" for k, v in SEVERITY_DEFINITIONS.items())


def _confidence_block():
    return "\n".join(
        f"  {level} ({CONFIDENCE_BANDS[level][0]}-{CONFIDENCE_BANDS[level][1]}%): "
        f"{CONFIDENCE_DEFINITIONS[level]}"
        for level in ("High", "Medium", "Low")
    )


# ------------------------------------------------------------------ Module 1
SYSTEM_PROMPT = f"""You are an AI-assisted UX heuristic evaluation assistant. You support human \
UX reviewers by producing consistent, evidence-based heuristic evaluations. You do not replace \
human judgment; your output is decision support that will be reviewed by a person.

CORE RULES (in force at every stage):
- Evaluate ONLY observable evidence. Do not invent user behaviour. Do not assume analytics. \
Do not assume business priorities. Never fabricate missing information.
- Do not measure satisfaction, NPS, conversion, or anything requiring real participants.
- Do not claim WCAG or accessibility COMPLIANCE — only observable accessible-design practices.
- When evidence is insufficient for a conclusion, mark it for human validation instead of \
presenting assumptions as facts. Favor transparency over completeness.
- Every finding follows this reasoning chain, never skipping a stage:
  Observed Evidence -> Usability Concern -> User Impact -> Severity -> Recommendation -> Priority.
- Each finding belongs to exactly ONE primary evaluation dimension.
- Positive elements with no usability concern are recorded as strengths/positive observations, \
never forced into findings.

THE EIGHT EVALUATION DIMENSIONS (weights sum to 100%):
{_dimension_table()}

SCORING SCALE (each dimension scored independently, 1-10):
{_score_scale()}

SEVERITY FRAMEWORK (severity reflects likely impact on users; it is independent of the \
dimension score and independent of confidence):
{_severity_block()}

CONFIDENCE FRAMEWORK (confidence measures certainty of the evidence, NOT importance; \
report a level and a percentage; high confidence does not imply high severity):
{_confidence_block()}

You will be guided through the evaluation one module at a time. Follow only the current \
module's instructions; do not run ahead (for example, never produce recommendations during \
evidence analysis or assessment)."""


# ------------------------------------------------------------------ Module 2
def m2_evidence_prompt(evidence_text, has_screenshots):
    visual_rule = (
        "Screenshots ARE provided: visual judgments (layout, hierarchy, contrast, "
        "whitespace) may be made from them at the confidence the evidence supports."
        if has_screenshots else
        "Screenshots are NOT provided — you are reasoning from page source/text only. "
        "Purely visual judgments (color contrast, whitespace, rendered layout, viewport "
        "position, aesthetic quality) cannot be directly observed: either mark such "
        "concerns validation_needed=true or omit them. Do not present visual claims "
        "as directly observed."
    )
    return f"""MODULE 2 — EVIDENCE ANALYSIS.

{visual_rule}

For each of the eight evaluation dimensions:
1. Review the available webpage evidence.
2. Assess the interface using that dimension's evaluation criteria.
3. Record observable strengths (at most 3, each a short phrase).
4. Record observable usability concerns (at most 3 per dimension — the most impactful \
ones) — each concern is ONE sentence, specific to this page, with ONE sentence of \
supporting evidence quoting/describing what is observable.
5. Assign a preliminary score (1-10) using the standardized scoring scale, or null with \
insufficient_evidence=true when the evidence cannot support a meaningful score.
6. Mark validation_needed=true on any concern that cannot be confirmed from this evidence.

Assign every concern a unique id: F1, F2, F3... sequential across ALL dimensions.

Do NOT assign severity or confidence. Do NOT generate recommendations. Do NOT speculate \
about user behaviour, business context, or analytics. Do NOT claim accessibility compliance.

EVIDENCE:
{evidence_text}

Record your analysis with the record_evidence_analysis tool."""


# ------------------------------------------------------------------ Module 3
def m3_assessment_prompt(m2_json):
    return f"""MODULE 3 — FINDING ASSESSMENT.

Below is the Module 2 evidence analysis. For EVERY concern (finding) listed, by its finding_id:
1. Review the supporting evidence.
2. Assess the likely user impact (one sentence, grounded in the evidence).
3. Determine severity using the Severity Framework.
4. Determine confidence using the Confidence Framework (level follows from the percentage).
5. Provide a brief justification for both assessments.
6. Set validation_required to the kind of human validation needed (user_testing, \
accessibility_review, analytics, stakeholder_input, technical_investigation) or "none".

Severity and confidence are INDEPENDENT: low confidence does not imply low severity, and \
high confidence does not imply high severity. Findings whose impact cannot be confidently \
determined get severity "Validation Needed". Concerns marked validation_needed=true in \
Module 2 must get validation_required != "none".

Do NOT generate recommendations. Do NOT add new findings. Do NOT re-score dimensions.

MODULE 2 OUTPUT:
{json.dumps(m2_json, indent=1)}

Record your assessments with the record_finding_assessments tool — one entry per finding_id."""


# ------------------------------------------------------------------ Module 4
def m4_recommendation_prompt(m3_json, findings_index):
    return f"""MODULE 4 — RECOMMENDATION GENERATION.

Below are the assessed findings. For EVERY finding, by its finding_id, generate exactly one \
recommendation that is:
- Evidence-based (traceable to the finding's observable evidence),
- Actionable and specific to this page,
- Proportional to the severity and the strength of the evidence,
- User-centred (framed around the expected user benefit),
- Practical for a small organization with limited UX resources.

For findings with severity "Validation Needed" (or validation_required != "none"), recommend \
the appropriate INVESTIGATION (is_investigation=true) — e.g. usability testing, accessibility \
review — not an implementation change.

Estimate implementation effort: Low (minor wording/layout/styling/content), Medium (moderate \
interface/navigation/workflow changes), High (significant redesign or structural work).

Assign priority: Priority 1 (Critical/High severity on essential tasks — immediate action), \
Priority 2 (Medium severity, noticeable friction — next improvement cycle), Priority 3 (Low \
severity or deferred enhancements). If you deviate from the severity-implied priority, you \
MUST provide priority_justification.

Do NOT introduce new findings. Do NOT change severity or confidence. Do NOT recommend \
changes unrelated to observed evidence.

FINDINGS (concern text + evidence by id):
{json.dumps(findings_index, indent=1)}

ASSESSMENTS (Module 3 output):
{json.dumps(m3_json, indent=1)}

Record with the record_recommendations tool — one entry per finding_id."""


# ------------------------------------------------------------------ Module 5
def m5_narrative_prompt(digest_json):
    return f"""MODULE 5 — STRUCTURED REPORT NARRATIVE.

The structured data of the report (dimension scores, findings, severities, confidences, \
recommendations, validation requirements) is assembled programmatically from the earlier \
modules and presented exactly as assessed — you must NOT restate, alter, or add to it.

Your task is ONLY the narrative prose, based strictly on the digest below:
- executive_summary: 3-4 short professional paragraphs — what was evaluated and how (an \
AI-assisted heuristic evaluation), the principal strengths observed, the main opportunity \
areas, and a one-line note that findings/recommendations follow the standardized methodology.
- overall_assessment: one sentence.
- key_observations: 2-6 bullets, drawn only from the digest.
- score_interpretation: one or two sentences interpreting the overall score and its band.
- evaluation_limitations: bullets covering missing evidence, unknown user behaviour, unknown \
analytics, unknown business priorities, and any dimensions that could not be scored.
- conclusion: brief; MUST state this is an AI-assisted heuristic evaluation that requires \
human review before action.
- next_steps: 1-5 suggested actions (highest-priority items first, validation needs included).

Introduce NO new findings, scores, or recommendations. Use cautious professional language.

EVALUATION DIGEST:
{json.dumps(digest_json, indent=1)}

Record with the record_report_narrative tool."""
