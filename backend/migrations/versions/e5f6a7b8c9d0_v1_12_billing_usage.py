"""v1.12 #18：token 级用量表 + 套餐/余额账户 + 账户流水

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-11 04:10:00

三张表都是 append-only 计量与账务：
- usage_records：每次 LLM 调用一条，成本按模型价表折算成分；
- accounts：账户快照（套餐 + 余额 + 当期 token 用量）；
- account_ledger：充值/订阅/退款流水，余额可由流水重放验证。
"""
import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_records",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=32), nullable=False),
        sa.Column("order_id", sa.String(length=32), nullable=True),
        sa.Column("job_id", sa.String(length=32), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_usage_records_tenant_id", "usage_records", ["tenant_id"])
    op.create_index("ix_usage_records_owner_id", "usage_records", ["owner_id"])
    op.create_index("ix_usage_records_owner_created", "usage_records",
                    ["owner_id", "created_at"])
    op.create_index("ix_usage_records_order_id", "usage_records", ["order_id"])

    op.create_table(
        "accounts",
        sa.Column("owner_id", sa.String(length=32), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("plan_key", sa.String(length=32), nullable=False, server_default="free"),
        sa.Column("balance_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("token_quota", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_accounts_tenant_id", "accounts", ["tenant_id"])
    op.create_index("ix_accounts_tenant_owner", "accounts", ["tenant_id", "owner_id"])

    op.create_table(
        "account_ledger",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("delta_cents", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_account_ledger_tenant_id", "account_ledger", ["tenant_id"])
    op.create_index("ix_account_ledger_owner_id", "account_ledger", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_account_ledger_owner_id", table_name="account_ledger")
    op.drop_index("ix_account_ledger_tenant_id", table_name="account_ledger")
    op.drop_table("account_ledger")
    op.drop_index("ix_accounts_tenant_owner", table_name="accounts")
    op.drop_index("ix_accounts_tenant_id", table_name="accounts")
    op.drop_table("accounts")
    op.drop_index("ix_usage_records_order_id", table_name="usage_records")
    op.drop_index("ix_usage_records_owner_created", table_name="usage_records")
    op.drop_index("ix_usage_records_owner_id", table_name="usage_records")
    op.drop_index("ix_usage_records_tenant_id", table_name="usage_records")
    op.drop_table("usage_records")
