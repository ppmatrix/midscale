"""Add relay sessions table for DERP-style relay fallback.

Revision ID: ae1b2c3d4e5f
Revises: 9d0e1f2a3b4c
Create Date: 2026-05-10 14:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "ae1b2c3d4e5f"
down_revision: Union[str, None] = "9d0e1f2a3b4c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "relay_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=sa.text("gen_random_uuid()")),
        sa.Column("initiator_device_id", UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False, index=True),
        sa.Column("target_device_id", UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False, index=True),
        sa.Column("relay_region", sa.String(64), nullable=False, default="default"),
        sa.Column("relay_node", sa.String(128), nullable=False, default="relay0"),
        sa.Column("relay_token", sa.String(255), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, default="pending", index=True),
        sa.Column("bytes_tx", sa.BigInteger(), nullable=False, default=0),
        sa.Column("bytes_rx", sa.BigInteger(), nullable=False, default=0),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("relay_sessions")
