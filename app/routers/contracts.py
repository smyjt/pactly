import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.exceptions import ContractNotFoundError, DuplicateContractError, UnsupportedFileTypeError
from app.schemas.contract import ContractResponse, ContractUploadResponse
from app.services.contract_service import ContractService

router = APIRouter(prefix="/contracts", tags=["contracts"])


def get_contract_service() -> ContractService:
    # Placeholder — overridden in main.py with real DB session injection
    raise NotImplementedError("Dependency override not configured")


@router.post("", response_model=ContractUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_contract(
    file: UploadFile = File(...),
    service: ContractService = Depends(get_contract_service),
):
    """Upload a PDF or DOCX contract for analysis."""
    try:
        return await service.upload_contract(file)
    except UnsupportedFileTypeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except DuplicateContractError:
        raise HTTPException(status_code=409, detail="This contract has already been uploaded.")


@router.get("/{contract_id}", response_model=ContractResponse)
async def get_contract(
    contract_id: uuid.UUID,
    service: ContractService = Depends(get_contract_service),
):
    """Get contract details and current processing status."""
    try:
        return await service.get_contract(contract_id)
    except ContractNotFoundError:
        raise HTTPException(status_code=404, detail=f"Contract {contract_id} not found.")


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contract(
    contract_id: uuid.UUID,
    service: ContractService = Depends(get_contract_service),
):
    """Delete a contract and all associated data (chunks, clauses, risk assessments)."""
    try:
        await service.delete_contract(contract_id)
    except ContractNotFoundError:
        raise HTTPException(status_code=404, detail=f"Contract {contract_id} not found.")
