"""make_chunk_embedding_nullable

Revision ID: 78791b1574ca
Revises: 7dace9c2408f
Create Date: 2026-02-21 10:43:44.214139

"""
from typing import Sequence, Union

import pgvector.sqlalchemy
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '78791b1574ca'
down_revision: Union[str, Sequence[str], None] = '7dace9c2408f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'contract_chunks', 'embedding',
        existing_type=pgvector.sqlalchemy.Vector(dim=1536),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        'contract_chunks', 'embedding',
        existing_type=pgvector.sqlalchemy.Vector(dim=1536),
        nullable=False,
    )
