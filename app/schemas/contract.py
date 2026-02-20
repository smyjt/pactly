import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ContractUploadResponse(BaseModel):
    """Returned immediately after a successful upload."""
    id: uuid.UUID
    filename: str
    status: Literal["pending", "processing", "completed", "failed"]
    message: str = "Contract uploaded. Processing will begin shortly."

    model_config = {"from_attributes": True}


class ContractResponse(BaseModel):
    """Full contract details including processing status."""
    id: uuid.UUID
    filename: str
    content_type: str
    status: Literal["pending", "processing", "completed", "failed"]
    page_count: int | None = None
    token_count: int | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
