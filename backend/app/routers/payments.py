"""支付订单：创建支付单 → 轮询 → 确认支付（解锁正文生成）。

对照原产品支付流（saveOrder→pay/payment→queryPayStatus 5s 轮询）：
- 金额一律取订单服务端价（客户端传什么都被忽略，逆向报告 P0 教训）；
- 状态轮询 GET /payments/{serial}；
- mock 模式（默认）：POST /payments/{serial}/confirm 模拟网关回调成功；
  manual 模式：确认只接受管理员（收到真实收款后人工放行）；
  真实商户 webhook v1.0 接入（provider_ref 已预留）。
- 支付成功 → WritingOrder.paid_at 落时间戳，正文生成/改写以此解锁。
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import PaymentOrder, WritingOrder
from ..tenancy import CurrentUser, current_user, ownership_filter

router = APIRouter(prefix="/payments", tags=["payments"])


async def _accrue_commission(db: AsyncSession, order: WritingOrder) -> dict | None:
    """订单首次支付成功时，按服务端价 × 代理 rate_bps 生成一条 pending 佣金（幂等）。"""
    from sqlalchemy import select as _select

    from ..models import Commission, Distributor

    if not order.distributor_code:
        return None
    dist = (await db.execute(
        _select(Distributor).where(Distributor.code == order.distributor_code,
                                   Distributor.status == "active")
    )).scalars().first()
    if dist is None:
        return None
    exists = (await db.execute(
        _select(Commission).where(Commission.order_id == order.id)
    )).scalars().first()
    if exists is not None:
        return {"commission_cents": exists.amount_cents, "duplicate": True}
    amount = int(order.price_cents * dist.rate_bps // 10000)
    db.add(Commission(tenant_id=order.tenant_id, distributor_id=dist.id,
                      order_id=order.id, order_amount_cents=order.price_cents,
                      rate_bps=dist.rate_bps, amount_cents=amount))
    return {"commission_cents": amount, "distributor_id": dist.id}

_PAY_METHODS = ("wechat", "alipay")


def _payment_out(p: PaymentOrder) -> dict:
    return {
        "serial_no": p.serial_no,
        "order_id": p.order_id,
        "amount_cents": p.amount_cents,
        "pay_method": p.pay_method,
        "status": p.status,
        "provider_ref": p.provider_ref,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "paid_at": p.paid_at.isoformat() if p.paid_at else None,
    }


class PayIn(BaseModel):
    pay_method: str = Field(pattern="^(wechat|alipay)$")


@router.post("/orders/{order_id}")
async def create_payment(order_id: str, body: PayIn,
                         db: AsyncSession = Depends(get_db),
                         user: CurrentUser = Depends(current_user)):
    order = (await db.execute(
        ownership_filter(select(WritingOrder), WritingOrder, user)
        .where(WritingOrder.id == order_id)
    )).scalar()
    if order is None:
        raise HTTPException(404, "订单不存在")
    if order.paid_at is not None:
        raise HTTPException(409, "订单已支付，不要重复支付")

    payment = PaymentOrder(
        serial_no=f"SC{uuid.uuid4().hex[:24].upper()}",
        tenant_id=user.tenant_id, owner_id=user.user_id, order_id=order.id,
        amount_cents=order.price_cents,  # 服务端价，body 不含金额字段
        pay_method=body.pay_method,
    )
    db.add(payment)
    await db.commit()
    return {**_payment_out(payment),
            "pay_url": f"https://pay.mock.scholar-copilot.local/{payment.serial_no}",
            "note": "mock 网关：自部署演示用；真实商户回调见 docs（v1.0 webhook）"}


@router.get("/{serial_no}")
async def payment_status(serial_no: str, db: AsyncSession = Depends(get_db),
                         user: CurrentUser = Depends(current_user)):
    payment = (await db.execute(
        ownership_filter(select(PaymentOrder), PaymentOrder, user)
        .where(PaymentOrder.serial_no == serial_no)
    )).scalar()
    if payment is None:
        raise HTTPException(404, "支付单不存在")
    return _payment_out(payment)


@router.post("/{serial_no}/confirm")
async def confirm_payment(serial_no: str, db: AsyncSession = Depends(get_db),
                          user: CurrentUser = Depends(current_user)):
    """mock 模式：付款人本人确认（模拟网关回调）；manual 模式：仅管理员。"""
    if settings.payment_mode == "manual" and user.role not in ("superadmin", "tenant_admin", "operator"):
        raise HTTPException(403, "manual 支付模式仅管理员可确认收款")

    payment = (await db.execute(
        ownership_filter(select(PaymentOrder), PaymentOrder, user)
        .where(PaymentOrder.serial_no == serial_no)
    )).scalar()
    if payment is None:
        if user.role in ("superadmin", "tenant_admin", "operator"):
            payment = (await db.execute(
                select(PaymentOrder).where(PaymentOrder.serial_no == serial_no)
            )).scalar()
        if payment is None:
            raise HTTPException(404, "支付单不存在")
    if payment.status == "paid":
        raise HTTPException(409, "该支付单已完成支付")

    payment.status = "paid"
    payment.paid_at = datetime.now(timezone.utc)
    payment.provider_ref = f"mock-{payment.serial_no}"
    order = await db.get(WritingOrder, payment.order_id)
    if order is not None:
        order.paid_at = payment.paid_at
        await _accrue_commission(db, order)
    await db.commit()
    return {**_payment_out(payment), "order_paid": order is not None}


@router.get("")
async def my_payments(db: AsyncSession = Depends(get_db),
                      user: CurrentUser = Depends(current_user)):
    rows = (await db.execute(
        ownership_filter(select(PaymentOrder), PaymentOrder, user)
        .order_by(PaymentOrder.created_at.desc())
    )).scalars().all()
    return [_payment_out(p) for p in rows]
