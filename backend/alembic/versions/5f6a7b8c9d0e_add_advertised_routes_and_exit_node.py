"""add advertised_routes and exit_node_id

Revision ID: 5f6a7b8c9d0e
Revises: 4a5b6c7d8e9f
Create Date: 2026-05-09 16:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "5f6a7b8c9d0e"
down_revision: Union[str, None] = "4a5b6c7d8e9f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "advertised_routes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "network_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("networks.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("prefix", sa.String(43), nullable=False),
        sa.Column("enabled", sa.Boolean(), default=False, nullable=False),
        sa.Column("approved", sa.Boolean(), default=False, nullable=False),
        sa.Column("is_exit_node", sa.Boolean(), default=False, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.add_column(
        "devices",
        sa.Column(
            "exit_node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id"),
            nullable=True,
            default=None,
        ),
    )


def downgrade() -> None:
    op.drop_column("devices", "exit_node_id")
    op.drop_table("advertised_routes")
