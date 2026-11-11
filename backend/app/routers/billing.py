"""配额/定价/用量/套餐（v1.12 #18）。价格公式与成本价表都开源可查。

原产品只告诉你「订单多少钱」，不告诉你「token 花在哪」。这里的三个端点分别回答：
GET /billing/quote   —— 这单多少钱（公式同源，前后端可各算一遍核对）
GET /billing/usage   —— token 花在哪个任务上（按 kind 聚合，自己可复算）
GET /billing/account —— 我是什么套餐、余额多少、当期用了多少 token
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..billing import (PLANS, apply_delta, ensure_account, usage_summary)
from ..config import settings
from ..db import get_db
from ..models import Account, AccountLedger, GroupBuy, GroupBuyMember, RedeemCode
from ..tenancy import CurrentUser, current_user
from ..writing.service import price_cents, quota_used

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/quote")
async def quote(education: str, word_count: int):
    """价格透明：同一公式前端后端各算一遍，不一致说明有人在中间动手脚。"""
    try:
        cents = price_cents(education, word_count)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"price_cents": cents, "currency": "CNY"}


@router.get("/quota")
async def quota(db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(current_user)):
    used = await quota_used(db, user.user_id)
    return {
        "kind": "outline",
        "limit": settings.free_outline_limit,
        "used": used,
        "remaining": max(settings.free_outline_limit - used, 0),
    }


# ── v1.12 #18：套餐 / 余额 / token 用量 ──────────────────────

class TopupIn(BaseModel):
    amount_cents: int = Field(gt=0, le=10_000_000)


@router.get("/plans")
async def list_plans(user: CurrentUser = Depends(current_user)):
    """套餐清单（按价格升序，前端直接渲染）。"""
    del user  # 只看目录，不需要身份；保留依赖以便统一鉴权行为
    plans = [{"key": key, **spec} for key, spec in PLANS.items()]
    plans.sort(key=lambda p: p["price_cents"])
    return {"plans": plans}


@router.get("/usage")
async def usage(db: AsyncSession = Depends(get_db),
                user: CurrentUser = Depends(current_user)):
    """token 级用量汇总（按任务类型聚合），费用按模型价表折算成分。"""
    return await usage_summary(db, user.user_id)


@router.get("/account")
async def account(db: AsyncSession = Depends(get_db),
                  user: CurrentUser = Depends(current_user)):
    row = await ensure_account(db, tenant_id=user.tenant_id, owner_id=user.user_id)
    await db.commit()
    history = (await db.execute(
        select(AccountLedger).where(AccountLedger.owner_id == user.user_id)
        .order_by(AccountLedger.created_at.desc()).limit(20)
    )).scalars().all()
    return {
        "plan_key": row.plan_key,
        "plan_label": PLANS.get(row.plan_key, {}).get("label", row.plan_key),
        "balance_cents": int(row.balance_cents),
        "token_quota": int(row.token_quota),
        "tokens_used": int(row.tokens_used),
        "tokens_remaining": max(int(row.token_quota) - int(row.tokens_used), 0),
        "over_quota": int(row.tokens_used) > int(row.token_quota),
        "history": [{"kind": h.kind, "delta_cents": h.delta_cents,
                     "balance_after": h.balance_after, "reason": h.reason,
                     "created_at": h.created_at.isoformat() if h.created_at else None}
                    for h in history],
    }


@router.post("/account/topup")
async def topup(body: TopupIn, db: AsyncSession = Depends(get_db),
                user: CurrentUser = Depends(current_user)):
    """充值（演示模式；生产应改为支付渠道回调后入账）。"""
    row = await apply_delta(db, tenant_id=user.tenant_id, owner_id=user.user_id,
                            kind="topup", delta_cents=body.amount_cents,
                            reason="用户充值")
    await db.commit()
    return {"balance_cents": int(row.balance_cents)}


@router.post("/plans/{plan_key}/subscribe")
async def subscribe(plan_key: str, db: AsyncSession = Depends(get_db),
                    user: CurrentUser = Depends(current_user)):
    plan = PLANS.get(plan_key)
    if plan is None:
        raise HTTPException(404, f"套餐不存在：{plan_key}")
    row = await ensure_account(db, tenant_id=user.tenant_id, owner_id=user.user_id)
    charge = int(plan["price_cents"])
    if int(row.balance_cents) < charge:
        raise HTTPException(402, f"余额不足：需要 {charge} 分，当前 {int(row.balance_cents)} 分")
    if charge > 0:
        await apply_delta(db, tenant_id=user.tenant_id, owner_id=user.user_id,
                          kind="subscribe", delta_cents=-charge,
                          reason=f"订阅 {plan['label']}")
    row.plan_key = plan_key
    row.token_quota = int(plan["token_quota"])
    await db.commit()
    return {"plan_key": plan_key, "charged_cents": charge,
            "balance_cents": int(row.balance_cents),
            "token_quota": int(row.token_quota)}


# ── v1.12 #17：兑换码 / 拼团 ────────────────────────────────

class RedeemIn(BaseModel):
    code: str = Field(min_length=4, max_length=32)


@router.post("/redeem")
async def redeem(body: RedeemIn, db: AsyncSession = Depends(get_db),
                 user: CurrentUser = Depends(current_user)):
    """兑成余额。一码一用：已用即 409，不存在 404。"""
    code = body.code.strip().upper()
    row = await db.get(RedeemCode, code)
    if row is None:
        raise HTTPException(404, "兑换码不存在")
    if row.used_by:
        raise HTTPException(409, "兑换码已被使用")
    row.used_by = user.user_id
    row.used_at = datetime.now(timezone.utc)
    account = await apply_delta(db, tenant_id=user.tenant_id, owner_id=user.user_id,
                                kind="redeem", delta_cents=int(row.amount_cents),
                                reason=f"兑换码 {code}")
    await db.commit()
    return {"code": code, "amount_cents": int(row.amount_cents),
            "balance_cents": int(account.balance_cents)}


class GroupBuyIn(BaseModel):
    plan_key: str
    required: int = Field(default=3, ge=2, le=20)
    group_price_cents: int = Field(ge=1, le=10_000_000)
    expires_in_minutes: int = Field(default=1440, ge=0, le=60 * 24 * 30)


def _gb_shape(gb: GroupBuy, members: list[str] | None = None) -> dict:
    return {"id": gb.id, "plan_key": gb.plan_key, "required": int(gb.required),
            "joined": int(gb.joined), "group_price_cents": int(gb.group_price_cents),
            "status": gb.status, "initiator_id": gb.initiator_id,
            "expires_at": gb.expires_at.isoformat() if gb.expires_at else None,
            "members": members or []}


@router.post("/group-buys", status_code=201)
async def create_group_buy(body: GroupBuyIn, db: AsyncSession = Depends(get_db),
                           user: CurrentUser = Depends(current_user)):
    if body.plan_key not in PLANS:
        raise HTTPException(404, f"套餐不存在：{body.plan_key}")
    gb = GroupBuy(tenant_id=user.tenant_id, plan_key=body.plan_key,
                  required=body.required, joined=1,
                  group_price_cents=body.group_price_cents,
                  initiator_id=user.user_id, status="open",
                  expires_at=datetime.now(timezone.utc)
                  + timedelta(minutes=body.expires_in_minutes))
    db.add(gb)
    await db.flush()
    db.add(GroupBuyMember(tenant_id=user.tenant_id, group_buy_id=gb.id,
                          owner_id=user.user_id))
    await db.commit()
    return _gb_shape(gb, [user.user_id])


@router.post("/group-buys/{gb_id}/join")
async def join_group_buy(gb_id: str, db: AsyncSession = Depends(get_db),
                         user: CurrentUser = Depends(current_user)):
    gb = await db.get(GroupBuy, gb_id)
    if gb is None:
        raise HTTPException(404, "拼团不存在")
    if gb.status == "settled":
        raise HTTPException(409, "拼团已结算")
    now = datetime.now(timezone.utc)
    expires = gb.expires_at
    if expires is not None and expires.tzinfo is None:  # SQLite 读回是 naive
        expires = expires.replace(tzinfo=timezone.utc)
    if expires is not None and expires <= now:
        gb.status = "expired"
        await db.commit()
        raise HTTPException(410, "拼团已过期")
    exists = (await db.execute(
        select(GroupBuyMember).where(GroupBuyMember.group_buy_id == gb_id,
                                    GroupBuyMember.owner_id == user.user_id)
    )).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(409, "你已在该拼团中")

    db.add(GroupBuyMember(tenant_id=gb.tenant_id, group_buy_id=gb_id,
                          owner_id=user.user_id))
    gb.joined = int(gb.joined) + 1
    members = [m for m in (await db.execute(
        select(GroupBuyMember.owner_id).where(GroupBuyMember.group_buy_id == gb_id)
    )).scalars().all()]

    if int(gb.joined) >= int(gb.required):
        # 凑满：全员按拼团价扣款并升级套餐；任一人余额不足则整团不结算
        charge = int(gb.group_price_cents)
        for owner in members:
            account = await ensure_account(db, tenant_id=gb.tenant_id, owner_id=owner)
            if int(account.balance_cents) < charge:
                await db.rollback()
                raise HTTPException(
                    402, f"成员 {owner} 余额不足：需要 {charge} 分，拼团未结算")
        for owner in members:
            await apply_delta(db, tenant_id=gb.tenant_id, owner_id=owner,
                              kind="group_buy", delta_cents=-charge,
                              reason=f"拼团 {gb_id}（{gb.plan_key}）")
            account = await db.get(Account, owner)
            account.plan_key = gb.plan_key
            account.token_quota = int(PLANS[gb.plan_key]["token_quota"])
        gb.status = "settled"
    await db.commit()
    return _gb_shape(gb, members)


@router.get("/group-buys/{gb_id}")
async def get_group_buy(gb_id: str, db: AsyncSession = Depends(get_db),
                        user: CurrentUser = Depends(current_user)):
    del user
    gb = await db.get(GroupBuy, gb_id)
    if gb is None:
        raise HTTPException(404, "拼团不存在")
    members = [m for m in (await db.execute(
        select(GroupBuyMember.owner_id).where(GroupBuyMember.group_buy_id == gb_id)
    )).scalars().all()]
    return _gb_shape(gb, members)
