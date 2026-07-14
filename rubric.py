"""
Evaluation framework — the single source of truth for dimensions, scales,
and deterministic computations (overall score, bands, priority defaults).

Everything here is lifted from the spec set in ../docs (Doc 1 §4, Doc 2
pp.5-25) with the ambiguity resolutions recorded in
../memory/ux-eval-system-knowledge.md. The LLM never does arithmetic:
score roll-ups, band labels, and clamping all happen in this module.
"""

# --- 8 evaluation dimensions, weights sum to 100 (Doc 1 p.14) --------------
DIMENSIONS = [
    {
        "key": "navigation_clarity",
        "label": "Navigation Clarity",
        "weight": 20,
        "criteria": [
            "Primary navigation is easy to locate", "Meaningful labels",
            "Users can tell where they are", "Content discoverability",
            "Logical organization", "Search availability",
            "Efficient movement between sections", "Breadcrumbs/orientation cues",
        ],
    },
    {
        "key": "visual_hierarchy",
        "label": "Visual Hierarchy",
        "weight": 15,
        "criteria": [
            "Heading hierarchy", "Typography", "White space",
            "Layout organization", "Visual emphasis", "CTA visibility",
            "Readability", "Content grouping", "Information prioritization",
        ],
    },
    {
        "key": "consistency_standards",
        "label": "Consistency & Standards",
        "weight": 15,
        "criteria": [
            "Button consistency", "Color and typography consistency",
            "Navigation consistency", "Icon and terminology consistency",
            "Layout consistency", "Predictable interaction patterns",
        ],
    },
    {
        "key": "feedback_visibility",
        "label": "Feedback & System Visibility",
        "weight": 10,
        "criteria": [
            "Confirmation messages", "Error messages", "Success messages",
            "Progress indicators", "Loading indicators", "Form feedback",
            "System status visibility",
        ],
    },
    {
        "key": "error_prevention",
        "label": "Error Prevention & Recovery",
        "weight": 10,
        "criteria": [
            "Form validation", "Error prevention", "Helpful guidance",
            "Recovery options", "Confirmation before destructive actions",
            "Error clarity", "Recoverability",
        ],
    },
    {
        "key": "accessibility_readability",
        "label": "Accessibility & Readability",
        "weight": 10,
        "criteria": [
            "Text readability", "Color contrast where observable",
            "Font size", "Heading structure", "Link clarity",
            "Alt text where visible",
        ],
    },
    {
        "key": "task_efficiency",
        "label": "Task Efficiency",
        "weight": 10,
        "criteria": [
            "Number of steps for key tasks", "Workflow clarity",
            "Form complexity", "Unnecessary interactions", "Task flow",
            "Overall efficiency",
        ],
    },
    {
        "key": "trust_credibility",
        "label": "Trust & Credibility",
        "weight": 10,
        "criteria": [
            "Professional presentation", "Contact information",
            "About information", "Branding consistency",
            "Security indicators where visible", "Content credibility",
            "Organizational transparency",
        ],
    },
]

DIMENSION_KEYS = [d["key"] for d in DIMENSIONS]
DIMENSION_BY_KEY = {d["key"]: d for d in DIMENSIONS}

# --- scoring scale, 1-10 (Doc 1 p.17) --------------------------------------
SCORE_BANDS = [
    (9, 10, "Excellent"),
    (7, 8, "Good"),
    (5, 6, "Needs Improvement"),
    (3, 4, "Poor"),
    (1, 2, "Critical Issue"),
]


def score_band(score):
    """Band label for a 1-10 score (float or int). None-safe."""
    if score is None:
        return "Validation Needed"
    s = round(float(score))
    for lo, hi, label in SCORE_BANDS:
        if lo <= s <= hi:
            return label
    return "Critical Issue" if s < 1 else "Excellent"


# --- severity, 5-level (Doc 1 p.18) -----------------------------------------
SEVERITY_LEVELS = ["Critical", "High", "Medium", "Low", "Validation Needed"]
SEVERITY_DEFINITIONS = {
    "Critical": "Prevents completion of an essential task or creates a major "
                "accessibility, trust, or functional barrier.",
    "High": "Creates significant difficulty and may cause users to abandon an "
            "important task.",
    "Medium": "Creates noticeable friction but does not prevent task completion.",
    "Low": "Minor wording, presentation, consistency, or usability issue.",
    "Validation Needed": "Evidence is insufficient to confidently determine impact.",
}

# --- confidence (Doc 1 p.19; overlaps resolved per knowledge file §3.2) -----
CONFIDENCE_LEVELS = ["High", "Medium", "Low"]
CONFIDENCE_BANDS = {  # inclusive percentage ranges after resolution
    "High": (80, 95),
    "Medium": (60, 79),
    "Low": (30, 59),
}
CONFIDENCE_DEFINITIONS = {
    "High": "Directly supported by observable webpage evidence.",
    "Medium": "Supported by strong observable evidence but still involves "
              "reasonable interpretation.",
    "Low": "Requires additional validation through analytics, user testing, "
           "stakeholder input, or accessibility testing.",
}


def clamp_confidence(percentage):
    """Clamp a model-supplied percentage into [30, 95] and derive the level
    from the resolved bands (level always follows percentage)."""
    try:
        p = int(round(float(percentage)))
    except (TypeError, ValueError):
        p = 50
    p = max(30, min(95, p))
    if p >= 80:
        return p, "High"
    if p >= 60:
        return p, "Medium"
    return p, "Low"


# --- effort & priority (Doc 2 pp.24-25) --------------------------------------
EFFORT_LEVELS = ["Low", "Medium", "High"]
PRIORITY_LEVELS = ["Priority 1", "Priority 2", "Priority 3"]
PRIORITY_MEANINGS = {
    "Priority 1": "Immediate Action",
    "Priority 2": "Planned Improvement",
    "Priority 3": "Future Enhancement",
}

_DEFAULT_PRIORITY = {
    "Critical": 1, "High": 1, "Medium": 2, "Low": 3, "Validation Needed": 3,
}


def clamp_priority(severity, model_priority, has_justification):
    """Deterministic default priority from severity (knowledge file §3.10):
    the model may deviate by ONE step WITH a justification; anything else is
    clamped to the default."""
    default = _DEFAULT_PRIORITY.get(severity, 3)
    try:
        p = int(model_priority)
    except (TypeError, ValueError):
        return default
    if p == default:
        return p
    if abs(p - default) == 1 and has_justification and 1 <= p <= 3:
        return p
    return default


# --- validation-requirement categories (Doc 4 p.5) ---------------------------
VALIDATION_TYPES = [
    "user_testing", "accessibility_review", "analytics",
    "stakeholder_input", "technical_investigation",
]
VALIDATION_LABELS = {
    "user_testing": "User testing",
    "accessibility_review": "Accessibility review",
    "analytics": "Analytics",
    "stakeholder_input": "Stakeholder validation",
    "technical_investigation": "Technical investigation",
}


# --- overall score -----------------------------------------------------------
def overall_score(scores_by_key):
    """Weighted mean of SCORED dimensions on the 1-10 scale, weights
    renormalized over the dimensions that have a numeric score (knowledge
    file §3.4). Returns (score_rounded_1dp | None, band_label)."""
    accum, total_weight = 0.0, 0
    for d in DIMENSIONS:
        s = scores_by_key.get(d["key"])
        if s is None:
            continue
        accum += float(s) * d["weight"]
        total_weight += d["weight"]
    if total_weight == 0:
        return None, "Validation Needed"
    score = round(accum / total_weight, 1)
    return score, score_band(score)
