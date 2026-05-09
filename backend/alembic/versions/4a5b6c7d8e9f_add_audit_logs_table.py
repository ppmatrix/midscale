"""add audit_logs table

Revision ID: 4a5b6c7d8e9f
Revises: 3d4e5f6a7b8c
Create Date: 2026-05-09 14:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '4a5b6c7d8e9f'
down_revision: Union[str, None] = '3d4e5f6a7b8c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('actor_id', sa.String(255), nullable=True),
        sa.Column('actor_type', sa.String(20), nullable=False, server_default='user'),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('target_type', sa.String(50), nullable=False, server_default='none'),
        sa.Column('target_id', sa.String(255), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_audit_logs_actor_id'), 'audit_logs', ['actor_id'])
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'])
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'])


def downgrade() -> None:
    op.drop_index(op.f('ix_audit_logs_created_at'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_actor_id'), table_name='audit_logs')
    op.drop_table('audit_logs')
