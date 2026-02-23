import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import ContractChunk


class ChunkRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_contract_id(self, contract_id: uuid.UUID) -> list[ContractChunk]:
        result = await self.session.execute(
            select(ContractChunk)
            .where(ContractChunk.contract_id == contract_id)
            .order_by(ContractChunk.chunk_index)
        )
        return list(result.scalars().all())

    async def bulk_update_embeddings(
        self, chunks: list[ContractChunk], embeddings: list[list[float]]
    ) -> None:
        for chunk, embedding in zip(chunks, embeddings):
            chunk.embedding = embedding
        await self.session.flush()

    async def bulk_create(
        self, contract_id: uuid.UUID, chunks: list[dict]
    ) -> list[ContractChunk]:
        """Insert multiple chunks in one flush. Each dict must have: chunk_index, content, token_count."""
        objects = [ContractChunk(contract_id=contract_id, **chunk) for chunk in chunks]
        self.session.add_all(objects)
        await self.session.flush()
        return objects
