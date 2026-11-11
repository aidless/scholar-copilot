"""v1.12 #10 学校格式模板库表 format_templates

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-10 21:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'format_templates',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('school', sa.String(length=128), nullable=False),
        sa.Column('degree', sa.String(length=32), nullable=False),
        sa.Column('spec_json', sa.JSON(), nullable=False),
        sa.Column('builtin', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_format_templates_tenant_id', 'format_templates', ['tenant_id'])
    op.create_index('ix_format_templates_tenant_key', 'format_templates',
                    ['tenant_id', 'key'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_format_templates_tenant_key', table_name='format_templates')
    op.drop_index('ix_format_templates_tenant_id', table_name='format_templates')
    op.drop_table('format_templates')
