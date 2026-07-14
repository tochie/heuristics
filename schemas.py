"""
JSON Schemas for each module's structured output (enforced via Anthropic
tool-use). The spec's prompt library defines outputs only as prose bullet
lists (knowledge file §3.1) — these schemas are the normative shapes.

Module 2: evidence analysis  -> dimensions, preliminary scores, concerns (F-ids)
Module 3: finding assessment -> severity + confidence + user impact per F-id
Module 4: recommendations    -> one rec per F-id
Module 5: report narrative   -> prose-only fields (all data assembled server-side)
"""

from rubric import DIMENSION_KEYS, SEVERITY_LEVELS, EFFORT_LEVELS, VALIDATION_TYPES

_FINDING_ID = {"type": "string", "pattern": "^F[0-9]{1,3}$"}

M2_EVIDENCE_ANALYSIS = {
    "name": "record_evidence_analysis",
    "description": "Record the Module 2 evidence analysis across all eight "
                   "evaluation dimensions.",
    "input_schema": {
        "type": "object",
        "required": ["page_purpose", "positive_observations", "dimensions"],
        "properties": {
            "page_purpose": {
                "type": "string",
                "description": "One or two sentences: what this page is for, "
                               "based only on observable evidence.",
            },
            "positive_observations": {
                "type": "array", "items": {"type": "string"},
                "description": "Page-level strengths worth reporting (elements "
                               "with no usability concern are recorded here, "
                               "never forced into findings).",
            },
            "dimensions": {
                "type": "array",
                "minItems": 8, "maxItems": 8,
                "items": {
                    "type": "object",
                    "required": ["key", "preliminary_score", "strengths",
                                 "concerns", "insufficient_evidence"],
                    "properties": {
                        "key": {"type": "string", "enum": DIMENSION_KEYS},
                        "preliminary_score": {
                            "type": ["integer", "null"],
                            "minimum": 1, "maximum": 10,
                            "description": "1-10, or null when evidence is "
                                           "insufficient for a meaningful score.",
                        },
                        "insufficient_evidence": {"type": "boolean"},
                        "strengths": {"type": "array",
                                      "items": {"type": "string"}},
                        "concerns": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["id", "concern",
                                             "supporting_evidence",
                                             "validation_needed"],
                                "properties": {
                                    "id": _FINDING_ID,
                                    "concern": {
                                        "type": "string",
                                        "description": "ONE sentence, specific "
                                                       "to this page.",
                                    },
                                    "supporting_evidence": {
                                        "type": "string",
                                        "description": "ONE sentence of "
                                                       "observable evidence.",
                                    },
                                    "validation_needed": {
                                        "type": "boolean",
                                        "description": "True when the concern "
                                                       "cannot be confirmed from "
                                                       "the available evidence.",
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}

M3_FINDING_ASSESSMENT = {
    "name": "record_finding_assessments",
    "description": "Record Module 3 severity and confidence assessments for "
                   "every finding from Module 2.",
    "input_schema": {
        "type": "object",
        "required": ["assessments"],
        "properties": {
            "assessments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["finding_id", "user_impact", "severity",
                                 "severity_justification", "confidence_percentage",
                                 "confidence_justification", "validation_required"],
                    "properties": {
                        "finding_id": _FINDING_ID,
                        "user_impact": {
                            "type": "string",
                            "description": "Likely effect on users, one sentence, "
                                           "grounded in the evidence.",
                        },
                        "severity": {"type": "string", "enum": SEVERITY_LEVELS},
                        "severity_justification": {"type": "string"},
                        "confidence_percentage": {
                            "type": "integer", "minimum": 30, "maximum": 95,
                        },
                        "confidence_justification": {"type": "string"},
                        "validation_required": {
                            "type": "string",
                            "enum": ["none"] + VALIDATION_TYPES,
                            "description": "What kind of human validation this "
                                           "finding needs, if any.",
                        },
                    },
                },
            },
        },
    },
}

M4_RECOMMENDATIONS = {
    "name": "record_recommendations",
    "description": "Record Module 4 recommendations — exactly one per finding.",
    "input_schema": {
        "type": "object",
        "required": ["recommendations"],
        "properties": {
            "recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["finding_id", "recommendation", "reasoning",
                                 "expected_user_benefit", "estimated_effort",
                                 "priority", "is_investigation"],
                    "properties": {
                        "finding_id": _FINDING_ID,
                        "recommendation": {
                            "type": "string",
                            "description": "Imperative, benefit-oriented, "
                                           "proportional to the evidence.",
                        },
                        "reasoning": {"type": "string"},
                        "expected_user_benefit": {"type": "string"},
                        "estimated_effort": {"type": "string",
                                             "enum": EFFORT_LEVELS},
                        "priority": {"type": "integer", "minimum": 1, "maximum": 3},
                        "priority_justification": {
                            "type": "string",
                            "description": "Required ONLY when deviating from "
                                           "the severity-default priority.",
                        },
                        "is_investigation": {
                            "type": "boolean",
                            "description": "True when this recommends validation/"
                                           "investigation rather than an "
                                           "implementation change.",
                        },
                    },
                },
            },
        },
    },
}

M5_REPORT_NARRATIVE = {
    "name": "record_report_narrative",
    "description": "Record the narrative prose for the structured report. Do "
                   "NOT restate individual findings — they are assembled "
                   "separately from Modules 2-4 verbatim.",
    "input_schema": {
        "type": "object",
        "required": ["executive_summary", "overall_assessment",
                     "key_observations", "score_interpretation",
                     "evaluation_limitations", "conclusion", "next_steps"],
        "properties": {
            "executive_summary": {
                "type": "string",
                "description": "3-4 short paragraphs: what was done, positives, "
                               "opportunity areas, methodology note.",
            },
            "overall_assessment": {"type": "string",
                                   "description": "One-sentence overall "
                                                  "usability assessment."},
            "key_observations": {"type": "array", "items": {"type": "string"},
                                 "minItems": 2, "maxItems": 6},
            "score_interpretation": {"type": "string"},
            "evaluation_limitations": {"type": "array",
                                       "items": {"type": "string"}},
            "conclusion": {
                "type": "string",
                "description": "Must state this is an AI-assisted heuristic "
                               "evaluation requiring human review.",
            },
            "next_steps": {"type": "array", "items": {"type": "string"},
                           "minItems": 1, "maxItems": 5},
        },
    },
}
