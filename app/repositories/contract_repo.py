import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract


class ContractRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> Contract:
        contract = Contract(**kwargs)
        self.session.add(contract)
        await self.session.flush()
        await self.session.refresh(contract)
        return contract

    async def get_by_id(self, contract_id: uuid.UUID) -> Contract | None:
        result = await self.session.execute(
            select(Contract).where(Contract.id == contract_id)
        )
        return result.scalar_one_or_none()

    async def get_by_file_hash(self, file_hash: str) -> Contract | None:
        result = await self.session.execute(
            select(Contract).where(Contract.file_hash == file_hash)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self, contract_id: uuid.UUID, status: str, error_message: str | None = None
    ) -> None:
        contract = await self.get_by_id(contract_id)
        if contract:
            contract.status = status
            if error_message:
                contract.error_message = error_message
            await self.session.flush()
