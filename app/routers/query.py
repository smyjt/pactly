import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.exceptions import ContractNotFoundError
from app.schemas.query import QueryRequest, QueryResponse
from app.services.query_service import QueryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contracts", tags=["Query Management"])


def get_query_service() -> QueryService:
    # Placeholder — overridden in main.py with real dependencies injected
    raise NotImplementedError("Dependency override not configured")


@router.post(
    "/{contract_id}/query",
    response_model=QueryResponse,
    status_code=status.HTTP_200_OK,
)
async def query_contract(
    contract_id: uuid.UUID,
    body: QueryRequest,
    service: QueryService = Depends(get_query_service),
):
    """Ask a free-text question about a contract. Returns a grounded answer with source excerpts."""
    logger.info(f"Query request: contract_id={contract_id} question={body.question!r}")
    try:
        result = await service.query(contract_id, body.question)
        logger.info(
            f"Query response: contract_id={contract_id} "
            f"sources={len(result.sources)} model={result.model}"
        )
        return result
    except ContractNotFoundError:
        raise HTTPException(status_code=404, detail=f"Contract {contract_id} not found.")
