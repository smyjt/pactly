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
    ) -> list[tuple[ContractChunk, float]]:
        """Return the top_k chunks most similar to the query embedding.

        Uses pgvector's cosine distance operator (<=>) — lower distance means
        more similar. Cosine distance is converted to similarity (1 - distance)
        so callers get an intuitive score where 1.0 = identical, 0.0 = opposite.
        """
        distance_expr = ContractChunk.embedding.op("<=>")(query_embedding).label("distance")
        result = await self.session.execute(
            select(ContractChunk, distance_expr)
            .where(ContractChunk.contract_id == contract_id)
            .where(ContractChunk.embedding.is_not(None))
            .order_by(distance_expr)
            .limit(top_k)
        )
        return [
            (chunk, round(1.0 - float(distance), 4))
            for chunk, distance in result.all()
        ]
