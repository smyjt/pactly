import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ClauseType = Literal[
    "termination",
    "liability",
    "indemnity",
    "payment",
    "confidentiality",
    "intellectual_property",
    "dispute_resolution",
    "governing_law",
    "force_majeure",
    "warranty",
    "limitation_of_liability",
    "non_compete",
    "assignment",
    "other",
]


class ExtractedClause(BaseModel):
    clause_type: ClauseType
    title: str = Field(..., max_length=500)
    content: str
    summary: str
    section_reference: str | None = None


class ClauseExtractionResult(BaseModel):
    clauses: list[ExtractedClause]


class ClauseResponse(BaseModel):
    id: uuid.UUID
    contract_id: uuid.UUID
    clause_type: ClauseType
    title: str
    content: str
    summary: str | None
    section_reference: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
