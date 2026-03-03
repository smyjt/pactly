import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["low", "medium", "high", "critical"]


class ClauseRiskLLMOutput(BaseModel):
    """Validates the JSON returned by the LLM for a single clause risk assessment.
    Flags come from the rule engine — we don't ask the LLM to produce them.
    """
    risk_score: float = Field(..., ge=0.0, le=1.0)
    explanation: str


class RiskAssessmentResponse(BaseModel):
    id: uuid.UUID
    risk_level: RiskLevel
    risk_score: float = Field(..., ge=0.0, le=1.0)
    rule_score: float = Field(..., ge=0.0, le=1.0)
    llm_score: float = Field(..., ge=0.0, le=1.0)
    explanation: str
    flags: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class ClauseWithRiskResponse(BaseModel):
    id: uuid.UUID
    contract_id: uuid.UUID
    clause_type: str
    title: str
    content: str
    summary: str | None
    section_reference: str | None
    created_at: datetime
    risk: RiskAssessmentResponse | None

    model_config = {"from_attributes": True}


class ContractAnalysisResponse(BaseModel):
    contract_id: uuid.UUID
    overall_risk_score: float = Field(..., ge=0.0, le=1.0)
    overall_risk_level: RiskLevel
    clause_count: int
    clauses: list[ClauseWithRiskResponse]
