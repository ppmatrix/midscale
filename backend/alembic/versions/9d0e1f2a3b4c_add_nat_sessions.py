"""Add NAT sessions table for hole punching coordination.

Revision ID: 9d0e1f2a3b4c
Revises: c3cdac7f1f30
Create Date: 2026-05-10 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "9d0e1f2a3b4c"
down_revision: Union[str, None] = "c3cdac7f1f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nat_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=sa.text("gen_random_uuid()")),
        sa.Column("initiator_device_id", UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False, index=True),
        sa.Column("target_device_id", UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False, index=True),
        sa.Column("state", sa.String(20), nullable=False, default="pending", index=True),
        sa.Column("selected_candidate", sa.JSON, nullable=True),
        sa.Column("connectivity_established", sa.Boolean, default=False, nullable=False),
        sa.Column("extra_metadata", sa.JSON, nullable=True, default=dict),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("nat_sessions")
