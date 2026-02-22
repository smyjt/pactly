import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clause import Clause


class ClauseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_contract_id(self, contract_id: uuid.UUID) -> list[Clause]:
        result = await self.session.execute(
            select(Clause).where(Clause.contract_id == contract_id).order_by(Clause.created_at)
        )
        return list(result.scalars().all())

    async def bulk_create(
        self, contract_id: uuid.UUID, clauses: list[dict]
    ) -> list[Clause]:
        """Insert multiple clauses in one flush."""
        objects = [Clause(contract_id=contract_id, **clause) for clause in clauses]
        self.session.add_all(objects)
        await self.session.flush()
        return objects
