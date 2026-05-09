"""add endpoint scoring fields

Revision ID: c3cdac7f1f30
Revises: 737e64bcc13f
Create Date: 2026-05-09 16:46:07.763503
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'c3cdac7f1f30'
down_revision: Union[str, None] = '737e64bcc13f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('device_endpoints', sa.Column('latency_ms', sa.Integer(), nullable=True))
    op.add_column('device_endpoints', sa.Column('reachable', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('device_endpoints', sa.Column('last_probe_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('device_endpoints', sa.Column('failure_count', sa.Integer(), nullable=False, server_default=sa.text('0')))
    op.add_column('device_endpoints', sa.Column('success_count', sa.Integer(), nullable=False, server_default=sa.text('0')))
    op.add_column('device_endpoints', sa.Column('score', sa.Integer(), nullable=False, server_default=sa.text('0')))


def downgrade() -> None:
    op.drop_column('device_endpoints', 'score')
    op.drop_column('device_endpoints', 'success_count')
    op.drop_column('device_endpoints', 'failure_count')
    op.drop_column('device_endpoints', 'last_probe_at')
    op.drop_column('device_endpoints', 'reachable')
    op.drop_column('device_endpoints', 'latency_ms')
