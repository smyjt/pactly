import json
import logging
import uuid
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ContractNotFoundError
from app.models.clause import Clause
from app.repositories.clause_repo import ClauseRepository
from app.repositories.contract_repo import ContractRepository
from app.repositories.llm_usage_log_repo import LLMUsageLogRepository
from app.repositories.risk_repo import RiskRepository
from app.schemas.risk import (
    ClauseRiskLLMOutput,
    ClauseWithRiskResponse,
    ContractAnalysisResponse,
    RiskAssessmentResponse,
)
from app.services.llm.base import LLMProvider
from app.services.llm.cost import estimate_llm_cost
from app.services.llm.prompts.risk_assessment import RISK_ASSESSMENT_SYSTEM, RISK_ASSESSMENT_USER
from app.services.risk_rules import score_clause

logger = logging.getLogger(__name__)

RiskLevel = Literal["low", "medium", "high", "critical"]

_RULE_WEIGHT = 0.4
_LLM_WEIGHT = 0.6
_MAX_OUTPUT_TOKENS = 200


def _risk_level(score: float) -> RiskLevel:
    if score < 0.25:
        return "low"
    if score < 0.50:
        return "medium"
    if score < 0.75:
        return "high"
    return "critical"


class RiskService:
    def __init__(self, session: AsyncSession, llm: LLMProvider, llm_provider_name: str):
        self.session = session
        self.llm = llm
        self.llm_provider_name = llm_provider_name
        self._contract_repo = ContractRepository(session)
        self._clause_repo = ClauseRepository(session)
        self._risk_repo = RiskRepository(session)
        self._log_repo = LLMUsageLogRepository(session)

    async def score_contract(self, contract_id: uuid.UUID) -> None:
        """Score all clauses for a contract. Called by the Celery task."""
        clauses = await self._clause_repo.get_by_contract_id(contract_id)
        if not clauses:
            logger.warning(f"[risk] No clauses found for contract={contract_id}")
            return

        logger.info(f"[risk] Scoring {len(clauses)} clauses for contract={contract_id}")
        assessments = [await self._score_clause(contract_id, c) for c in clauses]
        await self._risk_repo.bulk_create(assessments)
        logger.info(f"[risk] Saved {len(assessments)} assessments for contract={contract_id}")

    async def get_analysis(self, contract_id: uuid.UUID) -> ContractAnalysisResponse:
        """Return all clauses with risk scores and overall contract risk."""
        contract = await self._contract_repo.get_by_id(contract_id)
        if not contract:
            raise ContractNotFoundError(str(contract_id))

        clauses = await self._risk_repo.get_clauses_with_risk(contract_id)
        clause_responses = [_build_clause_response(c) for c in clauses]
        overall_score, overall_level = _compute_overall_risk(clause_responses)

        return ContractAnalysisResponse(
            contract_id=contract_id,
            overall_risk_score=overall_score,
            overall_risk_level=overall_level,
            clause_count=len(clauses),
            clauses=clause_responses,
        )

    async def _score_clause(self, contract_id: uuid.UUID, clause: Clause) -> dict:
        # Stage 1: rule engine — free and instant
        rule_score, flags = score_clause(clause.clause_type, clause.content)

        # Stage 2: LLM — flags passed as context so it focuses on explanation not re-detection
        messages = [
            {"role": "system", "content": RISK_ASSESSMENT_SYSTEM},
            {
                "role": "user",
                "content": RISK_ASSESSMENT_USER.format(
                    clause_type=clause.clause_type,
                    flags=flags if flags else "none detected",
                    content=clause.content,
                ),
            },
        ]

        response = await self.llm.complete(
            messages=messages,
            temperature=0.0,
            max_tokens=_MAX_OUTPUT_TOKENS,
            response_format={"type": "json_object"},
        )

        llm_output = ClauseRiskLLMOutput.model_validate(json.loads(response.content))

        await self._log_repo.create(
            contract_id=contract_id,
            provider=self.llm_provider_name,
            model=response.model,
            operation="risk_assessment",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=estimate_llm_cost(response.input_tokens, response.output_tokens, response.model),
            latency_ms=response.latency_ms,
            success=True,
        )

        combined_score = round(_RULE_WEIGHT * rule_score + _LLM_WEIGHT * llm_output.risk_score, 4)
        logger.info(
            f"[risk] clause={clause.id} type={clause.clause_type} "
            f"rule={rule_score} llm={llm_output.risk_score} combined={combined_score} flags={flags}"
        )

        return {
            "clause_id": clause.id,
            "risk_level": _risk_level(combined_score),
            "risk_score": combined_score,
            "rule_score": rule_score,
            "llm_score": llm_output.risk_score,
            "explanation": llm_output.explanation,
            "flags": flags,
        }


def _build_clause_response(clause: Clause) -> ClauseWithRiskResponse:
    risk = RiskAssessmentResponse.model_validate(clause.risk_assessment) if clause.risk_assessment else None
    return ClauseWithRiskResponse(
        id=clause.id,
        contract_id=clause.contract_id,
        clause_type=clause.clause_type,
        title=clause.title,
        content=clause.content,
        summary=clause.summary,
        section_reference=clause.section_reference,
        created_at=clause.created_at,
        risk=risk,
    )


def _compute_overall_risk(clauses: list[ClauseWithRiskResponse]) -> tuple[float, RiskLevel]:
    scored = [c.risk.risk_score for c in clauses if c.risk is not None]
    if not scored:
        return 0.0, "low"
    overall = round(0.3 * max(scored) + 0.7 * (sum(scored) / len(scored)), 4)
    return overall, _risk_level(overall)
