"""v1.12 #21：本地文献库（离线模式数据源）

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-11-11 06:10:00
"""
import sqlalchemy as sa
from alembic import op

revision = "g7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "local_references",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("authors_json", sa.JSON(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("venue", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("doi", sa.String(length=255), nullable=True),
        sa.Column("abstract", sa.Text(), nullable=False, server_default=""),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="journal"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_local_references_tenant_id", "local_references", ["tenant_id"])
    op.create_index("ix_local_references_owner_id", "local_references", ["owner_id"])
    op.create_index("ix_local_refs_owner_title", "local_references", ["owner_id", "title"])


def downgrade() -> None:
    op.drop_index("ix_local_refs_owner_title", table_name="local_references")
    op.drop_index("ix_local_references_owner_id", table_name="local_references")
    op.drop_index("ix_local_references_tenant_id", table_name="local_references")
    op.drop_table("local_references")
