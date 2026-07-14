"""
Deterministic report assembly + integrity enforcement (Doc 4 structure).

Everything numeric or structural happens HERE, not in the LLM: the overall
score, band labels, severity/confidence summaries, priority clamping,
finding<->recommendation links, and the Doc 4 quality checklist. Module 5
contributes narrative prose only — so "the report shall not introduce new
findings" is enforced structurally, not by trusting the model.
"""

from rubric import (
    DIMENSIONS, DIMENSION_BY_KEY, PRIORITY_MEANINGS, SEVERITY_LEVELS,
    VALIDATION_LABELS, clamp_confidence, clamp_priority, overall_score,
    score_band,
)

METHODOLOGY_SUMMARY = (
    "AI-assisted heuristic evaluation across eight weighted UX dimensions "
    "(derived from established usability principles), scored 1-10 per "
    "dimension. Each finding carries independent severity (Critical/High/"
    "Medium/Low/Validation Needed) and confidence (High/Medium/Low with a "
    "percentage). Recommendations are evidence-based and prioritized "
    "(Priority 1-3). Findings with insufficient evidence are flagged for "
    "human validation rather than asserted."
)


def _default_validation_type(dimension_key):
    return ("accessibility_review" if dimension_key == "accessibility_readability"
            else "user_testing")


def build_findings(m2, m3):
    """Join Module 2 concerns with Module 3 assessments into finding records.
    Missing assessments degrade to Validation Needed — never dropped."""
    assess_by_id = {a["finding_id"]: a for a in m3.get("assessments", [])}
    findings = []
    for dim in m2["dimensions"]:
        meta = DIMENSION_BY_KEY[dim["key"]]
        for concern in dim["concerns"]:
            fid = concern["id"]
            a = assess_by_id.get(fid)
            if a is None:
                a = {
                    "user_impact": "Not assessed — requires human validation.",
                    "severity": "Validation Needed",
                    "severity_justification": "The assessment stage did not "
                                              "return a result for this finding.",
                    "confidence_percentage": 30,
                    "confidence_justification": "No assessment available.",
                    "validation_required": _default_validation_type(dim["key"]),
                }
            severity = a.get("severity")
            if severity not in SEVERITY_LEVELS:
                severity = "Validation Needed"
            pct, level = clamp_confidence(a.get("confidence_percentage"))
            validation = a.get("validation_required", "none")
            if concern.get("validation_needed") and validation == "none":
                validation = _default_validation_type(dim["key"])
            if severity == "Validation Needed" and validation == "none":
                validation = _default_validation_type(dim["key"])
            findings.append({
                "id": fid,
                "dimension_key": dim["key"],
                "dimension": meta["label"],
                "finding": concern["concern"],
                "supporting_evidence": concern["supporting_evidence"],
                "user_impact": a.get("user_impact", ""),
                "severity": severity,
                "severity_justification": a.get("severity_justification", ""),
                "confidence_level": level,
                "confidence_percentage": pct,
                "confidence_justification": a.get("confidence_justification", ""),
                "validation_required": validation,
                "recommendation_ref": None,   # linked in build_recommendations
            })
    return findings


def build_recommendations(findings, m4):
    """Join Module 4 recs to findings (one per finding), clamp priorities,
    synthesize an investigation rec for any finding the model missed."""
    recs_by_id = {r["finding_id"]: r for r in m4.get("recommendations", [])}
    out = []
    for f in findings:
        r = recs_by_id.get(f["id"])
        if r is None:
            label = VALIDATION_LABELS.get(
                f["validation_required"], "further validation")
            r = {
                "recommendation": f"Validate this finding through "
                                  f"{label.lower()} before acting on it.",
                "reasoning": "No recommendation was generated; the safe "
                             "default is investigation.",
                "expected_user_benefit": "Ensures changes are grounded in "
                                         "validated user impact.",
                "estimated_effort": "Low",
                "priority": 3,
                "priority_justification": "",
                "is_investigation": True,
            }
        priority = clamp_priority(
            f["severity"], r.get("priority"),
            bool(str(r.get("priority_justification", "")).strip()))
        is_investigation = bool(r.get("is_investigation"))
        if f["severity"] == "Validation Needed":
            is_investigation = True
        rec_id = f"R-{f['id']}"
        f["recommendation_ref"] = rec_id
        out.append({
            "id": rec_id,
            "related_finding": f["id"],
            "dimension": f["dimension"],
            "recommendation": r.get("recommendation", ""),
            "reasoning": r.get("reasoning", ""),
            "expected_user_benefit": r.get("expected_user_benefit", ""),
            "estimated_effort": r.get("estimated_effort", "Medium"),
            "priority": f"Priority {priority}",
            "priority_meaning": PRIORITY_MEANINGS[f"Priority {priority}"],
            "is_investigation": is_investigation,
        })
    return out


def build_digest(inputs_meta, dim_rows, findings, recommendations, score, band):
    """Compact digest handed to Module 5 for narrative generation."""
    return {
        "website": inputs_meta.get("url") or "(content/screenshots supplied directly)",
        "page_title": inputs_meta.get("title", ""),
        "evidence_supplied": inputs_meta.get("evidence_supplied", []),
        "overall_score": score,
        "overall_band": band,
        "dimension_scores": [
            {"dimension": r["label"], "score": r["score"], "band": r["band"],
             "strengths": r["strengths"][:3], "concerns": r["concern_count"]}
            for r in dim_rows
        ],
        "positive_observations": inputs_meta.get("positive_observations", []),
        "findings_by_severity": _severity_counts(findings),
        "top_findings": [
            {"finding": f["finding"], "severity": f["severity"],
             "dimension": f["dimension"]}
            for f in sorted(findings, key=_severity_rank)[:6]
        ],
        "priority_1_recommendations": [
            r["recommendation"] for r in recommendations
            if r["priority"] == "Priority 1"
        ],
        "validation_needed": [
            {"finding": f["finding"],
             "validation": VALIDATION_LABELS.get(f["validation_required"], "")}
            for f in findings if f["validation_required"] != "none"
        ],
        "unscored_dimensions": [r["label"] for r in dim_rows if r["score"] is None],
        "screenshots_provided": inputs_meta.get("has_screenshots", False),
    }


def _severity_rank(f):
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3,
             "Validation Needed": 4}
    return order.get(f["severity"], 5)


def _severity_counts(findings):
    counts = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return counts


def assemble_report(inputs_meta, m2, findings, recommendations, narrative,
                    model):
    """The 10-section report (Doc 4 §4) + summaries, as one JSON object."""
    scores = {d["key"]: d["preliminary_score"] for d in m2["dimensions"]}
    score, band = overall_score(scores)

    dim_rows = []
    for d in DIMENSIONS:
        row = next(x for x in m2["dimensions"] if x["key"] == d["key"])
        dim_rows.append({
            "key": d["key"], "label": d["label"], "weight": d["weight"],
            "score": row["preliminary_score"],
            "band": score_band(row["preliminary_score"]),
            "strengths": row.get("strengths", []),
            "concern_count": len(row.get("concerns", [])),
            "insufficient_evidence": bool(row.get("insufficient_evidence")),
        })

    by_priority = {"Priority 1": [], "Priority 2": [], "Priority 3": []}
    for r in recommendations:
        by_priority[r["priority"]].append(r)

    validation_requirements = [
        {"finding_id": f["id"], "finding": f["finding"],
         "dimension": f["dimension"],
         "type": f["validation_required"],
         "label": VALIDATION_LABELS.get(f["validation_required"], "")}
        for f in findings if f["validation_required"] != "none"
    ]

    limitations = list(narrative.get("evaluation_limitations", []))
    if not inputs_meta.get("has_screenshots"):
        note = ("No screenshots were provided; purely visual qualities "
                "(rendered layout, contrast, whitespace) were not directly "
                "observable and are flagged for validation where relevant.")
        if not any("screenshot" in l.lower() for l in limitations):
            limitations.append(note)
    for label in (r["label"] for r in dim_rows if r["score"] is None):
        limitations.append(f"{label} could not be scored from the available "
                           f"evidence and is excluded from the weighted score.")

    report = {
        "meta": {
            "website": inputs_meta.get("url"),
            "page_title": inputs_meta.get("title", ""),
            "model": model,
            "methodology_version": "1.0",
            "scope": "Single page",
        },
        "executive_summary": {
            "website_reviewed": inputs_meta.get("url")
                                or "(content/screenshots supplied directly)",
            "evaluation_objective": "Assess the usability of the page against "
                                    "the standardized eight-dimension heuristic "
                                    "framework and produce prioritized, "
                                    "evidence-based recommendations.",
            "overall_ux_score": score,
            "overall_band": band,
            "overall_assessment": narrative.get("overall_assessment", ""),
            "key_observations": narrative.get("key_observations", []),
            "text": narrative.get("executive_summary", ""),
        },
        "evaluation_scope": {
            "website_evaluated": inputs_meta.get("url")
                                 or "(no URL — direct evidence)",
            "evidence_supplied": inputs_meta.get("evidence_supplied", []),
            "methodology": "AI-assisted heuristic evaluation",
            "scope_of_review": "Single page as supplied; multi-page flows, "
                               "analytics, user testing, and accessibility "
                               "conformance testing are out of scope.",
        },
        "methodology_summary": {
            "description": METHODOLOGY_SUMMARY,
            "dimensions": [{"label": d["label"], "weight": d["weight"]}
                           for d in DIMENSIONS],
        },
        "overall_ux_score": {
            "score": score,
            "band": band,
            "display": (f"{score} / 10 — {band}" if score is not None
                        else "Validation Needed"),
            "interpretation": narrative.get("score_interpretation", ""),
        },
        "dimension_scores": dim_rows,
        "detailed_findings": findings,
        "prioritized_recommendations": by_priority,
        "validation_requirements": validation_requirements,
        "evaluation_limitations": limitations,
        "conclusion": {
            "text": narrative.get("conclusion", ""),
            "next_steps": narrative.get("next_steps", []),
        },
        "severity_summary": _severity_counts(findings),
        "confidence_summary": _confidence_counts(findings),
    }
    _quality_check(report)
    return report


def _confidence_counts(findings):
    counts = {}
    for f in findings:
        counts[f["confidence_level"]] = counts.get(f["confidence_level"], 0) + 1
    return counts


def _quality_check(report):
    """Doc 4 §7 quality checklist as hard assertions (raise = bug, since every
    joiner above is total)."""
    assert len(report["dimension_scores"]) == 8, "all eight dimensions present"
    rec_ids = {r["id"] for rs in report["prioritized_recommendations"].values()
               for r in rs}
    for f in report["detailed_findings"]:
        assert f["supporting_evidence"], f"finding {f['id']} missing evidence"
        assert f["severity"], f"finding {f['id']} missing severity"
        assert f["confidence_level"], f"finding {f['id']} missing confidence"
        assert f["recommendation_ref"] in rec_ids, \
            f"finding {f['id']} not linked to a recommendation"
    finding_ids = {f["id"] for f in report["detailed_findings"]}
    for rs in report["prioritized_recommendations"].values():
        for r in rs:
            assert r["related_finding"] in finding_ids, \
                f"recommendation {r['id']} references unknown finding"
