# Phase 5: Risk Scoring Implementation Plan

**Goal:** Score every extracted clause using a hybrid engine (rule-based + LLM), store results in `risk_assessments`, and expose `GET /contracts/:id/analysis`.

**Architecture:** Two-stage scoring per clause. Stage 1: pure-Python rule engine scans for known risk patterns (free, deterministic). Stage 2: LLM reads the clause and returns a nuanced score + explanation. Final score = `0.4 × rule_score + 0.6 × llm_score`. Triggered automatically as the last step in the Celery chain. No new migration needed — `risk_assessments` table already exists.

---

## What is hybrid scoring and why?

**Rule-based alone** is fast and free but dumb — only catches patterns explicitly coded. Misses nuance.

**LLM alone** is smart but slow and costs money per call. Can be inconsistent without a baseline.

**Hybrid:** Rules catch known red flags cheaply and give the LLM pre-screened context. The LLM adds judgment on top. 40/60 weighting means neither dominates — the LLM has more influence but can't completely ignore a flagged clause.

**Why score per clause, not the whole contract?**
A contract might be low risk overall but contain one critical indemnity clause. Per-clause scoring surfaces that. Overall score is derived by aggregating up — you can always aggregate, you can't disaggregate.

## Risk Level Thresholds

| Score | Level |
|---|---|
| 0.00 – 0.25 | low |
| 0.25 – 0.50 | medium |
| 0.50 – 0.75 | high |
| 0.75 – 1.00 | critical |

---

## Task 1: Risk Schemas

**Files:** Create `app/schemas/risk.py`

```python
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["low", "medium", "high", "critical"]


class ClauseRiskLLMOutput(BaseModel):
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
```

---

> **Pause.**

---

## Task 2: Risk Repository

**Files:** Create `app/repositories/risk_repo.py`

**Why `selectinload`:** The analysis endpoint needs clauses AND their risk assessments together. `selectinload` tells SQLAlchemy to eagerly load the `risk_assessment` relationship automatically — one DB round trip instead of N+1 queries (one query per clause).

```python
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.clause import Clause
from app.models.risk_assessment import RiskAssessment


class RiskRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def bulk_create(self, assessments: list[dict]) -> list[RiskAssessment]:
        objects = [RiskAssessment(**a) for a in assessments]
        self.session.add_all(objects)
        await self.session.flush()
        return objects

    async def get_clauses_with_risk(self, contract_id: uuid.UUID) -> list[Clause]:
        result = await self.session.execute(
            select(Clause)
            .where(Clause.contract_id == contract_id)
            .options(selectinload(Clause.risk_assessment))
            .order_by(Clause.created_at)
        )
        return list(result.scalars().all())
```

---

> **Pause.**

---

## Task 3: Rule Engine

**Files:** Create `app/services/risk_rules.py`

**How it works:**
1. Each clause type has a baseline score (indemnity starts higher than governing_law)
2. High-risk keyword patterns add 0.2–0.4 to the score
3. Medium-risk patterns add 0.1–0.2
4. Score is clamped to 1.0, returned with matched flag labels

**Why separate from the LLM call?** Rules run in microseconds at zero cost. Running them first gives the LLM pre-screened context — flags are passed into the prompt so the LLM incorporates them into its explanation rather than re-discovering them.

```python
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
    """Run the rule engine on a clause. Returns (score, flags)."""
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
```

---

> **Pause.**

---

## Task 4: Risk Assessment Prompt

**Files:** Create `app/services/llm/prompts/risk_assessment.py`

We pass the rule engine's flags into the prompt — the LLM incorporates them into its explanation rather than re-detecting them. Temperature `0.0` for determinism.

```python
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
```

---

> **Pause.**

---

## Task 5: Risk Service

**Files:** Create `app/services/risk_service.py`

**Combining formula:**
- Per clause: `risk_score = 0.4 × rule_score + 0.6 × llm_score`
- Overall contract: `overall = 0.3 × max_clause_score + 0.7 × mean_clause_score`

The max term ensures one critical clause raises the overall score. The mean reflects general contract risk.

```python
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
        """Score all clauses for a contract. Called by Celery task."""
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
        rule_score, flags = score_clause(clause.clause_type, clause.content)

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
```

---

> **Pause.**

---

## Task 6: Add Risk Task to Celery Chain

**Files:** Modify `app/workers/contract_tasks.py`

Two changes:
1. Add `task_score_risk` to `build_processing_chain`
2. Move `status="completed"` from `task_generate_embeddings` to `task_score_risk` — a contract is only complete when all processing is done

**In `build_processing_chain`:**
```python
return celery_chain(
    task_extract_and_chunk.s(contract_id),
    task_extract_clauses.s(),
    task_generate_embeddings.s(),
    task_score_risk.s(),
)
```

**In `_generate_embeddings_async`, remove:**
```python
contract_repo = ContractRepository(session)
await contract_repo.update(cid, status="completed")
```

**New task to add at the bottom:**
```python
@celery_app.task(bind=True, max_retries=3, default_retry_delay=10, acks_late=True)
def task_score_risk(self, prev_result: dict) -> dict:
    """Score risk for all clauses and mark contract as completed."""
    contract_id = prev_result["contract_id"]
    logger.info(f"[score_risk] Starting for contract {contract_id}")
    return asyncio.run(_score_risk_async(self, contract_id))


async def _score_risk_async(task, contract_id: str) -> dict:
    from app.config import Settings
    from app.database import create_engine, create_session_factory
    from app.repositories.contract_repo import ContractRepository
    from app.services.llm.factory import create_llm_provider
    from app.services.risk_service import RiskService

    settings = Settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    cid = uuid.UUID(contract_id)

    try:
        async with factory() as session:
            risk_svc = RiskService(
                session=session,
                llm=create_llm_provider(settings),
                llm_provider_name=settings.LLM_PROVIDER,
            )
            await risk_svc.score_contract(cid)
            await ContractRepository(session).update(cid, status="completed")
            await session.commit()

        logger.info(f"[score_risk] Done for contract {contract_id}")
        return {"contract_id": contract_id}

    except MaxRetriesExceededError:
        await _mark_failed(factory, cid, "Max retries exceeded during risk scoring")
        raise

    except Exception as exc:
        logger.exception(f"[score_risk] Failed for contract {contract_id}: {exc}")
        try:
            raise task.retry(exc=exc)
        except MaxRetriesExceededError:
            await _mark_failed(factory, cid, str(exc))
            raise

    finally:
        await engine.dispose()
```

---

> **Pause.**

---

## Task 7: Analysis Router

**Files:** Create `app/routers/analysis.py`

```python
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.exceptions import ContractNotFoundError
from app.schemas.risk import ContractAnalysisResponse
from app.services.risk_service import RiskService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contracts", tags=["Analysis"])


def get_risk_service() -> RiskService:
    raise NotImplementedError("Dependency override not configured")


@router.get(
    "/{contract_id}/analysis",
    response_model=ContractAnalysisResponse,
    status_code=status.HTTP_200_OK,
)
async def get_analysis(
    contract_id: uuid.UUID,
    service: RiskService = Depends(get_risk_service),
):
    """Get full contract analysis: all clauses with risk scores and overall contract risk."""
    logger.info(f"Analysis request: contract_id={contract_id}")
    try:
        result = await service.get_analysis(contract_id)
        logger.info(
            f"Analysis response: contract_id={contract_id} "
            f"overall={result.overall_risk_level} clauses={result.clause_count}"
        )
        return result
    except ContractNotFoundError:
        raise HTTPException(status_code=404, detail=f"Contract {contract_id} not found.")
```

---

> **Pause.**

---

## Task 8: Wire into main.py

**Files:** Modify `app/main.py`

Add inside `create_app()` after existing router registrations:

```python
    from app.routers.analysis import router as analysis_router, get_risk_service
    from app.services.risk_service import RiskService

    async def get_risk_service_with_session(
        session: AsyncSession = Depends(get_session),
    ) -> RiskService:
        return RiskService(
            session=session,
            llm=create_llm_provider(settings),
            llm_provider_name=settings.LLM_PROVIDER,
        )

    application.include_router(analysis_router, prefix="/api/v1")
    application.dependency_overrides[get_risk_service] = get_risk_service_with_session
```

---

## Processing chain after Phase 5

```
Upload → extract text → chunk → extract clauses → generate embeddings → score risk → completed
```
