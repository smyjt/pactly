import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.clause import Clause
from app.models.risk_assessment import RiskAssessment


class RiskRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def bulk_create(self, assessments: list[dict]) -> list[RiskAssessment]:
        objects = [RiskAssessment(**a) for a in assessments]
        self.session.add_all(objects)
        await self.session.flush()
        return objects

    async def get_clauses_with_risk(self, contract_id: uuid.UUID) -> list[Clause]:
        """Fetch all clauses for a contract with risk assessments eagerly loaded.

        Uses selectinload to avoid N+1 queries — SQLAlchemy runs one query for
        clauses and one follow-up query for all their risk assessments, then
        stitches the results together in Python.
        """
        result = await self.session.execute(
            select(Clause)
            .where(Clause.contract_id == contract_id)
            .options(selectinload(Clause.risk_assessment))
            .order_by(Clause.created_at)
        )
        return list(result.scalars().all())
