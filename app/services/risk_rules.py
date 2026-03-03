# Baseline risk score by clause type.
# Some clause types carry inherent risk regardless of their content.
_TYPE_BASELINE: dict[str, float] = {
    "indemnity": 0.5,
    "liability": 0.4,
    "non_compete": 0.5,
    "intellectual_property": 0.35,
    "limitation_of_liability": 0.1,
    "termination": 0.25,
    "confidentiality": 0.25,
    "payment": 0.15,
    "warranty": 0.25,
    "assignment": 0.2,
    "dispute_resolution": 0.15,
    "governing_law": 0.1,
    "force_majeure": 0.15,
    "other": 0.15,
}

# (pattern, score_contribution, flag_label)
# High risk: shifts power heavily to one party or removes protections entirely
_HIGH_RISK_PATTERNS: list[tuple[str, float, str]] = [
    ("unlimited liability", 0.4, "unlimited_liability"),
    ("sole discretion", 0.3, "sole_discretion"),
    ("unilateral", 0.25, "unilateral_right"),
    ("waive all claims", 0.35, "waiver_of_claims"),
    ("irrevocable", 0.25, "irrevocable_obligation"),
    ("perpetual", 0.2, "perpetual_obligation"),
    ("indemnify and hold harmless", 0.3, "broad_indemnity"),
    ("no limitation", 0.35, "no_limitation_of_liability"),
    ("without notice", 0.3, "termination_without_notice"),
    ("immediately terminate", 0.25, "immediate_termination"),
]

# Medium risk: vague obligations or ambiguous language
_MEDIUM_RISK_PATTERNS: list[tuple[str, float, str]] = [
    ("reasonable efforts", 0.1, "vague_obligation_reasonable_efforts"),
    ("best efforts", 0.1, "vague_obligation_best_efforts"),
    ("may terminate", 0.15, "discretionary_termination"),
    ("subject to change", 0.15, "subject_to_change"),
    ("as determined by", 0.15, "unilateral_determination"),
    ("at its discretion", 0.2, "discretionary_right"),
    ("without cause", 0.2, "termination_without_cause"),
    ("non-refundable", 0.15, "non_refundable_payment"),
]


def score_clause(clause_type: str, content: str) -> tuple[float, list[str]]:
    """Run the rule engine on a clause. Returns (rule_score, flags).

    Score is the sum of the type baseline and all matched pattern contributions,
    clamped to 1.0. Flags are the labels of every matched pattern.
    """
    content_lower = content.lower()
    score = _TYPE_BASELINE.get(clause_type, 0.15)
    flags: list[str] = []

    for pattern, contribution, flag in _HIGH_RISK_PATTERNS:
        if pattern in content_lower:
            score += contribution
            flags.append(flag)

    for pattern, contribution, flag in _MEDIUM_RISK_PATTERNS:
        if pattern in content_lower:
            score += contribution
            flags.append(flag)

    return min(round(score, 4), 1.0), flags
