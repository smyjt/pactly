import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import ContractChunk


class ChunkRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def bulk_create(
        self, contract_id: uuid.UUID, chunks: list[dict]
    ) -> list[ContractChunk]:
        """Insert multiple chunks in one flush. Each dict must have: chunk_index, content, token_count."""
        objects = [ContractChunk(contract_id=contract_id, **chunk) for chunk in chunks]
        self.session.add_all(objects)
        await self.session.flush()
        return objects
