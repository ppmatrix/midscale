"""add node-owned key enrollment fields to devices

Revision ID: 6a7b8c9d0e1f
Revises: 5f6a7b8c9d0e
Create Date: 2026-05-09 18:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "6a7b8c9d0e1f"
down_revision: Union[str, None] = "5f6a7b8c9d0e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column(
            "is_node_owned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "devices",
        sa.Column(
            "device_token_hash",
            sa.String(255),
            nullable=True,
        ),
    )
    op.add_column(
        "devices",
        sa.Column(
            "enrollment_status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
    )
    op.add_column(
        "devices",
        sa.Column(
            "enrolled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "devices",
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "devices",
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("devices", "revoked_at")
    op.drop_column("devices", "last_seen_at")
    op.drop_column("devices", "enrolled_at")
    op.drop_column("devices", "enrollment_status")
    op.drop_column("devices", "device_token_hash")
    op.drop_column("devices", "is_node_owned")
