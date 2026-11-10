"""运营日报汇总（HTTP 端点与定时推送共用同一份计算）。

为什么抽出来：定时推送如果自己再写一遍 SQL，两处口径迟早漂移——日报数字与管理台
对不上是运维最难查的一类问题。所以 `/admin/reports/summary` 与定时推送都调这里。
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import GenerationJob, PaymentOrder, User, WritingOrder


async def summary(db: AsyncSession, days: int) -> dict:
    """近 N 天运营汇总（收入/新单/新用户/任务分布/token 用量）。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    revenue = int((await db.execute(
        select(func.coalesce(func.sum(PaymentOrder.amount_cents), 0))
        .where(PaymentOrder.status == "paid", PaymentOrder.created_at >= since))).scalar() or 0)
    orders_new = int((await db.execute(
        select(func.count()).select_from(WritingOrder)
        .where(WritingOrder.created_at >= since))).scalar() or 0)
    jobs_rows = (await db.execute(
        select(GenerationJob.status, func.count())
        .where(GenerationJob.created_at >= since)
        .group_by(GenerationJob.status))).all()
    tokens = (await db.execute(
        select(func.coalesce(func.sum(GenerationJob.tokens_in), 0),
               func.coalesce(func.sum(GenerationJob.tokens_out), 0))
        .where(GenerationJob.created_at >= since))).one()
    new_users = int((await db.execute(
        select(func.count()).select_from(User)
        .where(User.created_at >= since))).scalar() or 0)
    return {
        "window_days": days, "since": since.isoformat(),
        "revenue_cents": revenue, "orders_new": orders_new, "new_users": new_users,
        "jobs_by_status": {s: c for s, c in jobs_rows},
        "tokens_in": int(tokens[0] or 0), "tokens_out": int(tokens[1] or 0),
    }


def format_text(data: dict) -> str:
    """把汇总渲染成可直接贴到 IM 的纯文本（定时推送正文）。"""
    revenue = data["revenue_cents"] / 100
    jobs = "、".join(f"{k}={v}" for k, v in sorted(data["jobs_by_status"].items())) or "无"
    return (
        f"Scholar Copilot 运营日报（近 {data['window_days']} 天）\n"
        f"收入 ¥{revenue:.2f} ｜ 新订单 {data['orders_new']} ｜ 新用户 {data['new_users']}\n"
        f"生成任务 {jobs}\n"
        f"Token 用量 in={data['tokens_in']} out={data['tokens_out']}"
    )
