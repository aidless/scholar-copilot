"""v1.12 #14：导出产物归档表

Revision ID: h8c9d0e1f2a3
Revises: g7b8c9d0e1f2
Create Date: 2026-11-11 07:20:00
"""
import sqlalchemy as sa
from alembic import op

revision = "h8c9d0e1f2a3"
down_revision = "g7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "export_artifacts",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=32), nullable=False),
        sa.Column("order_id", sa.String(length=32), nullable=False),
        sa.Column("fmt", sa.String(length=16), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_export_artifacts_tenant_id", "export_artifacts", ["tenant_id"])
    op.create_index("ix_export_artifacts_owner_id", "export_artifacts", ["owner_id"])
    op.create_index("ix_export_artifacts_order_created", "export_artifacts",
                    ["order_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_export_artifacts_order_created", table_name="export_artifacts")
    op.drop_index("ix_export_artifacts_owner_id", table_name="export_artifacts")
    op.drop_index("ix_export_artifacts_tenant_id", table_name="export_artifacts")
    op.drop_table("export_artifacts")
