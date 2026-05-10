"""add owner_id to networks

Revision ID: 1ea06c46da06
Revises: ae1b2c3d4e5f
Create Date: 2026-05-10 12:28:45.614660
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '1ea06c46da06'
down_revision: Union[str, None] = 'ae1b2c3d4e5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('networks', sa.Column('owner_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_networks_owner_id'), 'networks', ['owner_id'], unique=False)
    op.create_foreign_key(None, 'networks', 'users', ['owner_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint(None, 'networks', type_='foreignkey')
    op.drop_index(op.f('ix_networks_owner_id'), table_name='networks')
    op.drop_column('networks', 'owner_id')
