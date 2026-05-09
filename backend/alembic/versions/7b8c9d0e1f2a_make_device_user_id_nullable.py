"""make device.user_id nullable for preauth-enrolled devices

Revision ID: 7b8c9d0e1f2a
Revises: 6a7b8c9d0e1f
Create Date: 2026-05-09 19:00:00.000000
"""
from typing import Sequence, Union
from alembic import op


revision: str = "7b8c9d0e1f2a"
down_revision: Union[str, None] = "6a7b8c9d0e1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("devices", "user_id", nullable=True)


def downgrade() -> None:
    op.alter_column("devices", "user_id", nullable=False)
