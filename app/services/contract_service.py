import hashlib
import uuid
from pathlib import Path

import aiofiles
from fastapi import UploadFile

from app.exceptions import ContractNotFoundError, DuplicateContractError, UnsupportedFileTypeError
from app.repositories.contract_repo import ContractRepository
from app.schemas.contract import ContractResponse, ContractUploadResponse
from app.workers.contract_tasks import process_contract

ALLOWED_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}

UPLOAD_DIR = Path("/app/uploads")


class ContractService:
    def __init__(self, repo: ContractRepository):
        self.repo = repo

    async def upload_contract(self, file: UploadFile) -> ContractUploadResponse:
        # 1. Validate file type
        if file.content_type not in ALLOWED_CONTENT_TYPES:
            raise UnsupportedFileTypeError(file.content_type or "unknown")

        # 2. Read file and compute SHA-256 hash
        content = await file.read()
        file_hash = hashlib.sha256(content).hexdigest()

        # 3. Reject duplicates
        existing = await self.repo.get_by_file_hash(file_hash)
        if existing:
            raise DuplicateContractError(file_hash)

        # 4. Save file to disk
        file_ext = ALLOWED_CONTENT_TYPES[file.content_type]
        file_id = uuid.uuid4()
        file_path = UPLOAD_DIR / f"{file_id}{file_ext}"
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(file_path, "wb") as f:
            await f.write(content)

        # 5. Create DB record
        contract = await self.repo.create(
            id=file_id,
            filename=file.filename or "unnamed",
            file_path=str(file_path),
            file_hash=file_hash,
            content_type=file.content_type,
            status="pending",
        )

        process_contract.delay(str(contract.id))

        return ContractUploadResponse(
            id=contract.id,
            filename=contract.filename,
            status=contract.status,
        )

    async def get_contract(self, contract_id: uuid.UUID) -> ContractResponse:
        contract = await self.repo.get_by_id(contract_id)
        if not contract:
            raise ContractNotFoundError(str(contract_id))
        return ContractResponse.model_validate(contract)
