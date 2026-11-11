"""v1.12 内容指纹链表 generation_provenance

Revision ID: c3d4e5f6a7b8
Revises: b2d3e4f5a6c7
Create Date: 2026-11-10 20:20:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2d3e4f5a6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'generation_provenance',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('order_id', sa.String(length=32), nullable=False),
        sa.Column('node_id', sa.String(length=32), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('content_sha256', sa.String(length=64), nullable=False),
        sa.Column('word_count', sa.Integer(), nullable=False),
        sa.Column('ai_level', sa.String(length=1), nullable=False),
        sa.Column('sim_to_prev', sa.Float(), nullable=True),
        sa.Column('job_id', sa.String(length=32), nullable=True),
        sa.Column('actor', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_generation_provenance_tenant_id', 'generation_provenance', ['tenant_id'])
    op.create_index('ix_generation_provenance_order_id', 'generation_provenance', ['order_id'])
    op.create_index('ix_generation_provenance_node_id', 'generation_provenance', ['node_id'])
    op.create_index('ix_generation_provenance_content_sha256', 'generation_provenance', ['content_sha256'])
    op.create_index('ix_generation_provenance_job_id', 'generation_provenance', ['job_id'])
    op.create_index('ix_prov_order_node', 'generation_provenance', ['order_id', 'node_id'])


def downgrade() -> None:
    op.drop_index('ix_prov_order_node', table_name='generation_provenance')
    op.drop_index('ix_generation_provenance_job_id', table_name='generation_provenance')
    op.drop_index('ix_generation_provenance_content_sha256', table_name='generation_provenance')
    op.drop_index('ix_generation_provenance_node_id', table_name='generation_provenance')
    op.drop_index('ix_generation_provenance_order_id', table_name='generation_provenance')
    op.drop_index('ix_generation_provenance_tenant_id', table_name='generation_provenance')
    op.drop_table('generation_provenance')
