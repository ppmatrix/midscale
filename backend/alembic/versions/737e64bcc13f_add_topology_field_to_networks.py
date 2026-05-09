"""add topology field to networks

Revision ID: 737e64bcc13f
Revises: 8c9d0e1f2a3b
Create Date: 2026-05-09 15:26:03.996867
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '737e64bcc13f'
down_revision: Union[str, None] = '8c9d0e1f2a3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('device_endpoints', sa.Column('local_ip', sa.String(length=45), nullable=True))
    op.add_column('device_endpoints', sa.Column('public_ip', sa.String(length=45), nullable=True))
    op.add_column('device_endpoints', sa.Column('priority', sa.Integer(), server_default='100', nullable=False))
    op.add_column('device_endpoints', sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False))
    op.create_index(op.f('ix_device_endpoints_device_id'), 'device_endpoints', ['device_id'], unique=False)
    op.add_column('networks', sa.Column('topology', sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column('networks', 'topology')
    op.drop_index(op.f('ix_device_endpoints_device_id'), table_name='device_endpoints')
    op.drop_column('device_endpoints', 'is_active')
    op.drop_column('device_endpoints', 'priority')
    op.drop_column('device_endpoints', 'public_ip')
    op.drop_column('device_endpoints', 'local_ip')
