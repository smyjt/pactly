import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import ContractChunk


class EmbeddingRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def similarity_search(
        self,
        contract_id: uuid.UUID,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[ContractChunk]:
        """Return the top_k chunks most similar to the query embedding.

        Uses pgvector's cosine distance operator (<=>) — lower distance means
        more similar. Filters to the given contract so results are always
        scoped to a single document.
        """
        result = await self.session.execute(
            select(ContractChunk)
            .where(ContractChunk.contract_id == contract_id)
            .where(ContractChunk.embedding.is_not(None))
            .order_by(ContractChunk.embedding.op("<=>")(query_embedding))
            .limit(top_k)
        )
        return list(result.scalars().all())
