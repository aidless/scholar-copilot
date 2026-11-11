"""计费与用量（v1.12 #18）：套餐价目、成本折算、token 级记账、账户服务。

设计取舍：
- 成本按 `llm.router.COST_TABLE` 折算，不另立一套价格表（否则路由换了模型、
  账单还是旧价，两边对不上）。
- 记账是 append-only：所有消费/充值走流水，账户余额只是「流水求和的快照」，
  便于复算（余额不对可以重放流水找出来）。
- fake provider 成本恒 0，本地演示不会凭空产生费用。
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .llm.router import COST_TABLE, _DEFAULT_COST
from .models import Account, AccountLedger, UsageRecord

# 套餐：price_cents 是一次订阅费用；token_quota 是当期 token 额度（in+out 合计）
PLANS: dict[str, dict] = {
    "free": {
        "label": "免费版", "price_cents": 0, "token_quota": 50_000,
        "features": ["大纲", "章节生成", "导出 DOCX", "引用核查"],
    },
    "pro": {
        "label": "专业版", "price_cents": 9_900, "token_quota": 2_000_000,
        "features": ["免费版全部", "摘要/改写", "PPT/图表", "学校模板", "证据链可视化"],
    },
    "team": {
        "label": "团队版", "price_cents": 49_900, "token_quota": 10_000_000,
        "features": ["专业版全部", "租户品牌", "分销佣金", "优先队列"],
    },
}
DEFAULT_PLAN = "free"


def cost_cents(model: str, tokens_in: int, tokens_out: int) -> int:
    """按价表把 token 折算成「分」；未知模型走路由模块的兜底单价。"""
    ci, co = COST_TABLE.get(model, _DEFAULT_COST)
    yuan = tokens_in / 1000 * ci + tokens_out / 1000 * co
    return int(round(yuan * 100))


async def record_usage(db: AsyncSession, *, tenant_id: str, owner_id: str,
                       kind: str, model: str, tokens_in: int, tokens_out: int,
                       order_id: str | None = None,
                       job_id: str | None = None) -> UsageRecord:
    """落一条用量 + 累加账户当期 tokens_used（不抛异常阻断生成）。"""
    row = UsageRecord(
        tenant_id=tenant_id, owner_id=owner_id, order_id=order_id, job_id=job_id,
        kind=kind, model=model or "", tokens_in=int(tokens_in or 0),
        tokens_out=int(tokens_out or 0),
        cost_cents=cost_cents(model or "", int(tokens_in or 0), int(tokens_out or 0)),
    )
    db.add(row)
    account = await db.get(Account, owner_id)
    if account is not None:
        account.tokens_used += row.tokens_in + row.tokens_out
    return row


async def ensure_account(db: AsyncSession, *, tenant_id: str, owner_id: str) -> Account:
    """账户不存在则按免费套餐建一个（幂等，注册时不强制建）。"""
    account = await db.get(Account, owner_id)
    if account is None:
        plan = PLANS[DEFAULT_PLAN]
        account = Account(owner_id=owner_id, tenant_id=tenant_id,
                          plan_key=DEFAULT_PLAN, balance_cents=0,
                          token_quota=plan["token_quota"], tokens_used=0)
        db.add(account)
        await db.flush()
    return account


async def apply_delta(db: AsyncSession, *, tenant_id: str, owner_id: str,
                      kind: str, delta_cents: int, reason: str = "") -> Account:
    """写一条流水并更新余额快照。"""
    account = await ensure_account(db, tenant_id=tenant_id, owner_id=owner_id)
    balance = int(account.balance_cents) + int(delta_cents)
    if balance < 0:
        raise ValueError("余额不足")
    account.balance_cents = balance
    db.add(AccountLedger(tenant_id=tenant_id, owner_id=owner_id, kind=kind,
                         delta_cents=int(delta_cents), balance_after=balance,
                         reason=reason))
    return account


async def usage_summary(db: AsyncSession, owner_id: str) -> dict:
    """按 kind 聚合一个用户的全部用量。"""
    rows = (await db.execute(
        select(UsageRecord.kind,
               func.count(UsageRecord.id),
               func.coalesce(func.sum(UsageRecord.tokens_in), 0),
               func.coalesce(func.sum(UsageRecord.tokens_out), 0),
               func.coalesce(func.sum(UsageRecord.cost_cents), 0))
        .where(UsageRecord.owner_id == owner_id)
        .group_by(UsageRecord.kind).order_by(UsageRecord.kind)
    )).all()
    by_kind = [{"kind": r[0], "calls": int(r[1]), "tokens_in": int(r[2]),
                "tokens_out": int(r[3]), "cost_cents": int(r[4])} for r in rows]
    return {
        "total_calls": sum(x["calls"] for x in by_kind),
        "total_tokens_in": sum(x["tokens_in"] for x in by_kind),
        "total_tokens_out": sum(x["tokens_out"] for x in by_kind),
        "total_cost_cents": sum(x["cost_cents"] for x in by_kind),
        "by_kind": by_kind,
    }
