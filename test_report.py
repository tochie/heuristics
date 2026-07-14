"""Offline tests for the deterministic layer (no network, no API key).
Run: python3 -m pytest test_report.py -q"""

from report import assemble_report, build_findings, build_recommendations
from rubric import clamp_confidence, clamp_priority, overall_score, score_band


def test_overall_score_full_and_renormalized():
    full = {k: 7 for k in (
        "navigation_clarity", "visual_hierarchy", "consistency_standards",
        "feedback_visibility", "error_prevention", "accessibility_readability",
        "task_efficiency", "trust_credibility")}
    score, band = overall_score(full)
    assert score == 7.0 and band == "Good"
    # drop two dimensions -> weights renormalize over the scored ones
    partial = dict(full, error_prevention=None, task_efficiency=None)
    score, band = overall_score(partial)
    assert score == 7.0
    # heavier dimension pulls harder after renormalization
    skewed = dict(partial, navigation_clarity=10)
    score, _ = overall_score(skewed)
    assert score == round((10 * 20 + 7 * 60) / 80, 1)
    assert overall_score({k: None for k in full}) == (None, "Validation Needed")


def test_score_bands():
    assert score_band(10) == "Excellent"
    assert score_band(7) == "Good"
    assert score_band(5) == "Needs Improvement"
    assert score_band(3) == "Poor"
    assert score_band(1) == "Critical Issue"
    assert score_band(None) == "Validation Needed"


def test_clamp_confidence_resolved_bands():
    assert clamp_confidence(90) == (90, "High")
    assert clamp_confidence(80) == (80, "High")      # boundary -> higher band
    assert clamp_confidence(79) == (79, "Medium")
    assert clamp_confidence(60) == (60, "Medium")
    assert clamp_confidence(59) == (59, "Low")
    assert clamp_confidence(99) == (95, "High")      # clamped into [30, 95]
    assert clamp_confidence(5) == (30, "Low")
    assert clamp_confidence(None) == (50, "Low")


def test_clamp_priority_one_step_with_justification():
    assert clamp_priority("Critical", 1, False) == 1
    assert clamp_priority("Medium", 2, False) == 2
    assert clamp_priority("Medium", 1, True) == 1    # one step + justification
    assert clamp_priority("Medium", 1, False) == 2   # one step, no justification
    assert clamp_priority("Low", 1, True) == 3       # two steps -> clamped
    assert clamp_priority("Validation Needed", None, False) == 3


def _m2():
    dims = []
    for key in ("navigation_clarity", "visual_hierarchy",
                "consistency_standards", "feedback_visibility",
                "error_prevention", "accessibility_readability",
                "task_efficiency", "trust_credibility"):
        dims.append({"key": key, "preliminary_score": 7,
                     "insufficient_evidence": False,
                     "strengths": ["ok"], "concerns": []})
    dims[0]["concerns"] = [
        {"id": "F1", "concern": "Menu labels are ambiguous.",
         "supporting_evidence": "Nav items labelled 'Stuff' and 'Things'.",
         "validation_needed": False},
    ]
    dims[5]["preliminary_score"] = None
    dims[5]["insufficient_evidence"] = True
    dims[5]["concerns"] = [
        {"id": "F2", "concern": "Contrast may be insufficient.",
         "supporting_evidence": "Light gray text classes observed in source.",
         "validation_needed": True},
    ]
    return {"dimensions": dims, "positive_observations": ["Clean structure"],
            "page_purpose": "Marketing site"}


def _m3():
    return {"assessments": [
        {"finding_id": "F1", "user_impact": "Users struggle to find sections.",
         "severity": "Medium", "severity_justification": "Noticeable friction.",
         "confidence_percentage": 85, "confidence_justification": "Observable.",
         "validation_required": "none"},
        # F2 deliberately missing -> must degrade to Validation Needed
    ]}


def _m4():
    return {"recommendations": [
        {"finding_id": "F1", "recommendation": "Rename nav items descriptively.",
         "reasoning": "Ambiguity blocks wayfinding.",
         "expected_user_benefit": "Faster orientation.",
         "estimated_effort": "Low", "priority": 2,
         "priority_justification": "", "is_investigation": False},
    ]}


def test_join_and_assemble_report_integrity():
    m2 = _m2()
    findings = build_findings(m2, _m3())
    assert len(findings) == 2
    f2 = next(f for f in findings if f["id"] == "F2")
    assert f2["severity"] == "Validation Needed"           # degraded, not dropped
    assert f2["validation_required"] == "accessibility_review"
    recs = build_recommendations(findings, _m4())
    assert len(recs) == 2                                   # synthesized for F2
    r2 = next(r for r in recs if r["related_finding"] == "F2")
    assert r2["is_investigation"] and r2["priority"] == "Priority 3"

    report = assemble_report(
        {"url": "https://example.com", "title": "Example",
         "evidence_supplied": ["Website URL"], "has_screenshots": False,
         "positive_observations": m2["positive_observations"]},
        m2, findings, recs,
        {"executive_summary": "Summary.", "overall_assessment": "Decent.",
         "key_observations": ["a", "b"], "score_interpretation": "Good overall.",
         "evaluation_limitations": ["No analytics."],
         "conclusion": "AI-assisted; needs human review.",
         "next_steps": ["Fix nav"]},
        "test-model")

    assert len(report["dimension_scores"]) == 8
    # a11y dimension unscored -> excluded from weighted score (others all 7)
    assert report["overall_ux_score"]["score"] == 7.0
    assert report["overall_ux_score"]["display"] == "7.0 / 10 — Good"
    # bidirectional links
    f1 = next(f for f in report["detailed_findings"] if f["id"] == "F1")
    assert f1["recommendation_ref"] == "R-F1"
    assert report["severity_summary"] == {"Medium": 1, "Validation Needed": 1}
    assert any("could not be scored" in l for l in report["evaluation_limitations"])
    assert any("screenshot" in l.lower() for l in report["evaluation_limitations"])
    assert len(report["validation_requirements"]) == 1
