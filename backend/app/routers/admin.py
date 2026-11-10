"""多租户管理端（修复原产品洞 P1-1：匿名 Vue 管理台 + 弱口令 + 无审计）。

安全默认：
- 登录换 admin JWT（role 字段进 token；user 角色 403）；
- 登录失败统一 401（不区分账号不存在/密码错，防枚举）；
- 每个写动作落 admin_audit_log；
- 初始管理员密码从环境注入（SC_ADMIN_INITIAL_PASSWORD），空则不创建——
  没有默认口令，杜绝「admin/123456」式裸奔。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (AdminAuditLog, AdminUser, GenerationJob, PaymentOrder,
                      User, WritingOrder)
from ..security import make_token, verify_password
from ..tenancy import CurrentUser, admin_user

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminLoginIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)


@router.post("/login")
async def admin_login(body: AdminLoginIn, db: AsyncSession = Depends(get_db)):
    admin = (await db.execute(
        select(AdminUser).where(AdminUser.login_name == body.username)
    )).scalar()
    # 统一 401：不区分「账号不存在」与「密码错误」（防枚举，对照 auth.login 纪律）
    if admin is None or admin.status != "active" or not verify_password(body.password, admin.pass_hash):
        raise HTTPException(401, "用户名或密码错误")
    return {"access_token": make_token(admin.id, admin.tenant_id or "primary",
                                       role=admin.role),
            "role": admin.role}


async def _audit(db: AsyncSession, admin: CurrentUser, action: str,
                 target: dict, detail: dict | None = None) -> None:
    db.add(AdminAuditLog(admin_id=admin.user_id, action=action,
                         target=target, detail=detail))


@router.get("/users")
async def list_users(tenant: str | None = None, db: AsyncSession = Depends(get_db),
                     admin: CurrentUser = Depends(admin_user)):
    stmt = select(User).order_by(User.created_at.desc())
    if tenant:
        stmt = stmt.where(User.tenant_id == tenant)
    rows = (await db.execute(stmt)).scalars().all()
    return [{"id": u.id, "tenant_id": u.tenant_id, "phone": u.phone,
             "created_at": u.created_at.isoformat() if u.created_at else None}
            for u in rows]


@router.get("/orders")
async def list_orders(tenant: str | None = None, db: AsyncSession = Depends(get_db),
                      admin: CurrentUser = Depends(admin_user)):
    stmt = select(WritingOrder).order_by(WritingOrder.created_at.desc())
    if tenant:
        stmt = stmt.where(WritingOrder.tenant_id == tenant)
    rows = (await db.execute(stmt)).scalars().all()
    return [{"id": o.id, "tenant_id": o.tenant_id, "owner_id": o.owner_id,
             "title": o.title, "education": o.education, "status": o.status,
             "price_cents": o.price_cents, "paid_at": o.paid_at.isoformat() if o.paid_at else None,
             "created_at": o.created_at.isoformat() if o.created_at else None}
            for o in rows]


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db),
                admin: CurrentUser = Depends(admin_user)):
    async def count(model):
        return (await db.execute(select(func.count()).select_from(model))).scalar()
    paid_sum = (await db.execute(
        select(func.coalesce(func.sum(PaymentOrder.amount_cents), 0))
        .where(PaymentOrder.status == "paid")
    )).scalar()
    return {
        "users": await count(User),
        "orders": await count(WritingOrder),
        "jobs": await count(GenerationJob),
        "payments_total": await count(PaymentOrder),
        "payments_paid": (await db.execute(
            select(func.count()).select_from(PaymentOrder)
            .where(PaymentOrder.status == "paid"))).scalar(),
        "revenue_cents": int(paid_sum),
    }


@router.get("/payments")
async def list_payments(status: str | None = None,
                        db: AsyncSession = Depends(get_db),
                        admin: CurrentUser = Depends(admin_user)):
    stmt = select(PaymentOrder).order_by(PaymentOrder.created_at.desc())
    if status:
        stmt = stmt.where(PaymentOrder.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return [{"serial_no": p.serial_no, "order_id": p.order_id, "tenant_id": p.tenant_id,
             "owner_id": p.owner_id, "amount_cents": p.amount_cents,
             "pay_method": p.pay_method, "status": p.status,
             "paid_at": p.paid_at.isoformat() if p.paid_at else None}
            for p in rows]


class QuotaAdjustIn(BaseModel):
    user_id: str
    kind: str = Field(default="outline", pattern="^(outline)$")
    delta: int  # 正数赠送，负数回收
    reason: str = Field(min_length=2, max_length=200)


@router.post("/quota/adjust")
async def quota_adjust(body: QuotaAdjustIn, db: AsyncSession = Depends(get_db),
                       admin: CurrentUser = Depends(admin_user)):
    """人工调配额：写 append-only 台账（赠送/回收全留痕），不动 limit。"""
    user = await db.get(User, body.user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")
    from ..models import QuotaLedger
    db.add(QuotaLedger(tenant_id=user.tenant_id, user_id=user.id,
                       kind=body.kind, delta=body.delta, is_usage=False,
                       reason=f"admin 调整：{body.reason}"))
    await _audit(db, admin, "quota.adjust",
                 target={"user_id": user.id, "kind": body.kind},
                 detail={"delta": body.delta, "reason": body.reason})
    await db.commit()
    return {"adjusted": True, "user_id": body.user_id, "delta": body.delta}


@router.get("/audit-log")
async def audit_log(db: AsyncSession = Depends(get_db),
                    admin: CurrentUser = Depends(admin_user)):
    rows = (await db.execute(
        select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc())
    )).scalars().all()
    return [{"id": r.id, "admin_id": r.admin_id, "action": r.action,
             "target": r.target, "detail": r.detail,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows]
