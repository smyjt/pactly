RISK_ASSESSMENT_SYSTEM = """\
You are a legal risk analyst. Assess risk from the perspective of the party signing the contract.
High risk means the clause is unfavourable, vague, or removes important protections.
Low risk means the clause is standard, balanced, or protective.
Return valid JSON only. No explanation outside the JSON.\
"""

RISK_ASSESSMENT_USER = """\
Assess the risk of the following contract clause.

Clause type: {clause_type}
Pre-detected risk flags: {flags}

Clause content:
{content}

Return JSON in exactly this format:
{{"risk_score": <float 0.0-1.0>, "explanation": "<1-2 sentences explaining the risk level>"}}
\
"""
