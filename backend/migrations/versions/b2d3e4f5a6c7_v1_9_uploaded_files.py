"""v1.9 uploaded_files（对象存储元数据）

新增 uploaded_files 表：用户上传文件（开题报告/降重稿/排版模板）的元数据，
内容落对象存储（local/S3），本表只存 storage_key + sha256。

Revision ID: b2d3e4f5a6c7
Revises: a7c1e2d4f6b8
Create Date: 2026-11-10 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b2d3e4f5a6c7'
down_revision = 'a7c1e2d4f6b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'uploaded_files',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('owner_id', sa.String(length=32), nullable=False),
        sa.Column('order_id', sa.String(length=32), nullable=True),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('content_type', sa.String(length=128), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('storage_key', sa.String(length=255), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_uploaded_files_tenant_id'), 'uploaded_files', ['tenant_id'])
    op.create_index(op.f('ix_uploaded_files_owner_id'), 'uploaded_files', ['owner_id'])
    op.create_index(op.f('ix_uploaded_files_order_id'), 'uploaded_files', ['order_id'])
    op.create_index(op.f('ix_uploaded_files_sha256'), 'uploaded_files', ['sha256'])


def downgrade() -> None:
    op.drop_index(op.f('ix_uploaded_files_sha256'), table_name='uploaded_files')
    op.drop_index(op.f('ix_uploaded_files_order_id'), table_name='uploaded_files')
    op.drop_index(op.f('ix_uploaded_files_owner_id'), table_name='uploaded_files')
    op.drop_index(op.f('ix_uploaded_files_tenant_id'), table_name='uploaded_files')
    op.drop_table('uploaded_files')
