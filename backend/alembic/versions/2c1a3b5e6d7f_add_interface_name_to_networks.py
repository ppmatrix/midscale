"""add interface_name to networks

Revision ID: 2c1a3b5e6d7f
Revises: e44cb5174045
Create Date: 2026-05-09 10:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '2c1a3b5e6d7f'
down_revision: Union[str, None] = 'e44cb5174045'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'networks',
        sa.Column('interface_name', sa.String(length=15), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('networks', 'interface_name')
