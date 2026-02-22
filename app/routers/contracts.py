import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.exceptions import ContractNotFoundError, DuplicateContractError, UnsupportedFileTypeError
from app.schemas.contract import ContractResponse, ContractUploadResponse
from app.services.contract_service import ContractService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contracts", tags=["Contract Management"])


def get_contract_service() -> ContractService:
    # Placeholder — overridden in main.py with real DB session injection
    raise NotImplementedError("Dependency override not configured")


@router.post("", response_model=ContractUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_contract(
    file: UploadFile = File(...),
    service: ContractService = Depends(get_contract_service),
):
    """Upload a PDF or DOCX contract for analysis."""
    logger.info(f"Upload request received: filename={file.filename!r} content_type={file.content_type!r}")
    try:
        result = await service.upload_contract(file)
        logger.info(f"Upload accepted: contract_id={result.id} filename={result.filename!r} status={result.status}")
        return result
    except UnsupportedFileTypeError as e:
        logger.warning(f"Upload rejected — unsupported file type: {file.content_type!r}")
        raise HTTPException(status_code=422, detail=str(e))
    except DuplicateContractError:
        logger.warning(f"Upload rejected — duplicate file: filename={file.filename!r}")
        raise HTTPException(status_code=409, detail="This contract has already been uploaded.")


@router.get("/{contract_id}", response_model=ContractResponse)
async def get_contract(
    contract_id: uuid.UUID,
    service: ContractService = Depends(get_contract_service),
):
    """Get contract details and current processing status."""
    logger.info(f"Get contract: contract_id={contract_id}")
    try:
        result = await service.get_contract(contract_id)
        logger.info(f"Get contract response: contract_id={contract_id} status={result.status}")
        return result
    except ContractNotFoundError:
        logger.warning(f"Get contract — not found: contract_id={contract_id}")
        raise HTTPException(status_code=404, detail=f"Contract {contract_id} not found.")


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contract(
    contract_id: uuid.UUID,
    service: ContractService = Depends(get_contract_service),
):
    """Delete a contract and all associated data (chunks, clauses, risk assessments)."""
    logger.info(f"Delete contract: contract_id={contract_id}")
    try:
        await service.delete_contract(contract_id)
        logger.info(f"Delete contract success: contract_id={contract_id}")
    except ContractNotFoundError:
        logger.warning(f"Delete contract — not found: contract_id={contract_id}")
        raise HTTPException(status_code=404, detail=f"Contract {contract_id} not found.")
