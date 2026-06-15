"""
UX heuristic rubric — the single source of truth for what we score.

Mirrors the metrics document: 8 weighted metrics (weights sum to 100),
each scored 0-10. The overall score is the weighted average. Confidence is
metadata about each finding (High / Medium / Low), NOT part of the UX score.
"""

# Each metric: key, display label, weight (%), and the concrete signals the
# AI should look for (lifted from the "AI Looks For" lists in the doc).
METRICS = [
    {
        "key": "navigation_clarity",
        "label": "Navigation Clarity",
        "weight": 20,
        "looks_for": [
            "Clear menu labels",
            "Search visibility",
            "Breadcrumbs",
            "Logical information architecture",
            "Consistent navigation placement",
            "Navigation depth",
        ],
    },
    {
        "key": "visual_hierarchy",
        "label": "Visual Hierarchy",
        "weight": 15,
        "looks_for": [
            "Heading hierarchy",
            "Content grouping",
            "CTA prominence",
            "Visual clutter",
            "White space usage",
            "Scannability",
        ],
    },
    {
        "key": "consistency_standards",
        "label": "Consistency & Standards",
        "weight": 15,
        "looks_for": [
            "Consistent button styles",
            "Uniform interaction patterns",
            "Consistent terminology",
            "Standard layouts",
            "Predictable behavior",
        ],
    },
    {
        "key": "feedback_visibility",
        "label": "Feedback & System Visibility",
        "weight": 10,
        "looks_for": [
            "Loading indicators",
            "Progress bars",
            "Success messages",
            "Error notifications",
            "System status feedback",
        ],
    },
    {
        "key": "error_prevention",
        "label": "Error Prevention & Recovery",
        "weight": 10,
        "looks_for": [
            "Inline validation",
            "Error messaging",
            "Confirmation dialogs",
            "Undo options",
            "Form safeguards",
        ],
    },
    {
        "key": "accessibility_readability",
        "label": "Accessibility & Readability",
        "weight": 10,
        "looks_for": [
            "Color contrast",
            "Heading structure",
            "Alt text",
            "Readability",
            "Font size",
            "Keyboard accessibility indicators",
        ],
    },
    {
        "key": "task_efficiency",
        "label": "Task Efficiency",
        "weight": 10,
        "looks_for": [
            "Number of task steps",
            "CTA visibility",
            "Form length",
            "Interaction friction",
            "Click depth",
            "Mobile efficiency",
        ],
    },
    {
        "key": "trust_credibility",
        "label": "Trust & Credibility",
        "weight": 10,
        "looks_for": [
            "Contact information",
            "Security indicators",
            "Privacy information",
            "Testimonials",
            "Transparency signals",
            "Professional design quality",
        ],
    },
]

# Confidence is evidence-tier metadata, never folded into the score.
CONFIDENCE_RULES = (
    "HIGH  - Finding directly visible/observable in the page source "
    "(e.g. missing alt text, missing labels, no heading structure).\n"
    "MEDIUM - Finding inferred from UI structure "
    "(e.g. long forms, many nav items, competing CTAs).\n"
    "LOW   - Finding requires real user validation "
    "(e.g. trust, satisfaction, conversion likelihood)."
)


def weighted_overall(scores_by_key):
    """Weighted average of 0-10 metric scores, returned on a 0-100 scale.

    scores_by_key: {metric_key: score_0_to_10}. Missing metrics are skipped
    and the weights renormalized so a partial result still produces a number.
    """
    total_weight = 0
    accum = 0.0
    for m in METRICS:
        s = scores_by_key.get(m["key"])
        if s is None:
            continue
        accum += s * m["weight"]
        total_weight += m["weight"]
    if total_weight == 0:
        return 0.0
    # scores are 0-10, weights sum (when complete) to 100 -> *10 gives 0-100
    return round((accum / total_weight) * 10, 1)
