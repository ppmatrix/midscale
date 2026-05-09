"""add device_token_prefix column for optimized token lookup

Revision ID: 8c9d0e1f2a3b
Revises: 7b8c9d0e1f2a
Create Date: 2026-05-09 20:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "8c9d0e1f2a3b"
down_revision: Union[str, None] = "7b8c9d0e1f2a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("device_token_prefix", sa.String(16), nullable=True))
    op.create_index(op.f("ix_devices_device_token_prefix"), "devices", ["device_token_prefix"])


def downgrade() -> None:
    op.drop_index(op.f("ix_devices_device_token_prefix"), table_name="devices")
    op.drop_column("devices", "device_token_prefix")
