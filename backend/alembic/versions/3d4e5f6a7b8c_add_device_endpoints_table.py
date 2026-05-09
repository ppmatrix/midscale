"""add device_endpoints table

Revision ID: 3d4e5f6a7b8c
Revises: 2c1a3b5e6d7f
Create Date: 2026-05-09 12:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '3d4e5f6a7b8c'
down_revision: Union[str, None] = '2c1a3b5e6d7f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'device_endpoints',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('device_id', sa.UUID(), nullable=False),
        sa.Column('endpoint', sa.String(length=255), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('device_endpoints')
