import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.exceptions import ContractNotFoundError
from app.schemas.risk import ContractAnalysisResponse
from app.services.risk_service import RiskService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contracts", tags=["Risk Assessment"])


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
