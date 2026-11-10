"""分销代理端：登录（推广码 + 手机号）→ 看佣金 → 申请提现。

风控要点（对照原产品 transferMoney 无审计）：
- 佣金只能在订单支付成功时生成，金额 = 服务端价 × rate_bps，客户端不可传；
- 提现申请不得超可提现余额（已结算佣金 − 已申请/已付）；
- 每次管理端放款都写 admin_audit_log。
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Commission, Distributor, DistributorTransfer
from ..security import make_token
from ..tenancy import CurrentUser, distributor_user

router = APIRouter(prefix="/distributor", tags=["distributor"])


class DistLoginIn(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    phone: str = Field(min_length=6, max_length=32)


@router.post("/login")
async def dist_login(body: DistLoginIn, db: AsyncSession = Depends(get_db)):
    dist = (await db.execute(
        select(Distributor).where(Distributor.code == body.code)
    )).scalars().first()
    # 统一 401：不区分「码不存在」与「手机号不匹配」（防枚举）
    if dist is None or dist.status != "active" or dist.phone != body.phone:
        raise HTTPException(401, "推广码或手机号错误")
    return {"access_token": make_token(dist.id, dist.tenant_id, role="distributor"),
            "distributor_id": dist.id, "code": dist.code}


async def _me(db: AsyncSession, user: CurrentUser) -> Distributor:
    dist = await db.get(Distributor, user.user_id)
    if dist is None:
        raise HTTPException(404, "代理不存在")
    return dist


async def _sum(db: AsyncSession, stmt) -> int:
    return int((await db.execute(stmt)).scalar() or 0)


@router.get("/me")
async def dist_me(db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(distributor_user)):
    dist = await _me(db, user)
    settled = await _sum(db, select(func.coalesce(func.sum(Commission.amount_cents), 0))
                         .where(Commission.distributor_id == dist.id, Commission.status == "settled"))
    pending = await _sum(db, select(func.coalesce(func.sum(Commission.amount_cents), 0))
                         .where(Commission.distributor_id == dist.id, Commission.status == "pending"))
    requested = await _sum(db, select(func.coalesce(func.sum(DistributorTransfer.amount_cents), 0))
                           .where(DistributorTransfer.distributor_id == dist.id,
                                  DistributorTransfer.status.in_(("requested", "paid"))))
    return {
        "distributor_id": dist.id, "name": dist.name, "code": dist.code,
        "rate_bps": dist.rate_bps, "balance_cents": dist.balance_cents,
        "commission_settled_cents": settled, "commission_pending_cents": pending,
        "withdrawable_cents": max(settled - requested, 0),
    }


@router.get("/commissions")
async def dist_commissions(db: AsyncSession = Depends(get_db),
                          user: CurrentUser = Depends(distributor_user)):
    dist = await _me(db, user)
    rows = (await db.execute(
        select(Commission).where(Commission.distributor_id == dist.id)
        .order_by(Commission.created_at.desc()).limit(200)
    )).scalars().all()
    return [{"id": c.id, "order_id": c.order_id, "order_amount_cents": c.order_amount_cents,
             "rate_bps": c.rate_bps, "amount_cents": c.amount_cents, "status": c.status,
             "created_at": c.created_at.isoformat() if c.created_at else None} for c in rows]


class TransferIn(BaseModel):
    amount_cents: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=200)


@router.post("/transfers")
async def request_transfer(body: TransferIn, db: AsyncSession = Depends(get_db),
                           user: CurrentUser = Depends(distributor_user)):
    dist = await _me(db, user)
    settled = await _sum(db, select(func.coalesce(func.sum(Commission.amount_cents), 0))
                         .where(Commission.distributor_id == dist.id, Commission.status == "settled"))
    requested = await _sum(db, select(func.coalesce(func.sum(DistributorTransfer.amount_cents), 0))
                           .where(DistributorTransfer.distributor_id == dist.id,
                                  DistributorTransfer.status.in_(("requested", "paid"))))
    withdrawable = max(settled - requested, 0)
    if body.amount_cents > withdrawable:
        raise HTTPException(400, f"可提现余额不足（当前 {withdrawable} 分）")
    row = DistributorTransfer(tenant_id=dist.tenant_id, distributor_id=dist.id,
                              amount_cents=body.amount_cents, note=body.note)
    db.add(row)
    await db.commit()
    return {"id": row.id, "amount_cents": row.amount_cents, "status": row.status}


@router.get("/transfers")
async def list_transfers(db: AsyncSession = Depends(get_db),
                         user: CurrentUser = Depends(distributor_user)):
    dist = await _me(db, user)
    rows = (await db.execute(
        select(DistributorTransfer).where(DistributorTransfer.distributor_id == dist.id)
        .order_by(DistributorTransfer.created_at.desc()).limit(100)
    )).scalars().all()
    return [{"id": r.id, "amount_cents": r.amount_cents, "status": r.status,
             "note": r.note, "created_at": r.created_at.isoformat() if r.created_at else None,
             "paid_at": r.paid_at.isoformat() if r.paid_at else None} for r in rows]
