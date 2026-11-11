"""v1.12 #17：兑换码 + 拼团

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-11-11 05:05:00
"""
import sqlalchemy as sa
from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "redeem_codes",
        sa.Column("code", sa.String(length=32), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("batch", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("used_by", sa.String(length=32), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_redeem_codes_tenant_id", "redeem_codes", ["tenant_id"])
    op.create_index("ix_redeem_codes_batch", "redeem_codes", ["batch"])
    op.create_index("ix_redeem_codes_used_by", "redeem_codes", ["used_by"])

    op.create_table(
        "group_buys",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("plan_key", sa.String(length=32), nullable=False),
        sa.Column("required", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("joined", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("group_price_cents", sa.Integer(), nullable=False),
        sa.Column("initiator_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_group_buys_tenant_id", "group_buys", ["tenant_id"])
    op.create_index("ix_group_buys_initiator_id", "group_buys", ["initiator_id"])

    op.create_table(
        "group_buy_members",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("group_buy_id", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_group_buy_members_tenant_id", "group_buy_members", ["tenant_id"])
    op.create_index("ix_group_buy_members_group_buy_id", "group_buy_members", ["group_buy_id"])
    op.create_index("ix_group_buy_members_owner_id", "group_buy_members", ["owner_id"])
    op.create_index("ix_group_buy_members_gb_owner", "group_buy_members",
                    ["group_buy_id", "owner_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_group_buy_members_gb_owner", table_name="group_buy_members")
    op.drop_index("ix_group_buy_members_owner_id", table_name="group_buy_members")
    op.drop_index("ix_group_buy_members_group_buy_id", table_name="group_buy_members")
    op.drop_index("ix_group_buy_members_tenant_id", table_name="group_buy_members")
    op.drop_table("group_buy_members")
    op.drop_index("ix_group_buys_initiator_id", table_name="group_buys")
    op.drop_index("ix_group_buys_tenant_id", table_name="group_buys")
    op.drop_table("group_buys")
    op.drop_index("ix_redeem_codes_used_by", table_name="redeem_codes")
    op.drop_index("ix_redeem_codes_batch", table_name="redeem_codes")
    op.drop_index("ix_redeem_codes_tenant_id", table_name="redeem_codes")
    op.drop_table("redeem_codes")
