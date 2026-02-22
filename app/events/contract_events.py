import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class ContractUploaded:
    contract_id: uuid.UUID
    filename: str
