import uuid

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=5, max_length=1000)


class SourceChunk(BaseModel):
    chunk_index: int
    content: str
    similarity_score: float = Field(..., ge=0.0, le=1.0)


class QueryResponse(BaseModel):
    contract_id: uuid.UUID
    question: str
    answer: str
    sources: list[SourceChunk]
    model: str
    input_tokens: int
    output_tokens: int
