"""多租户管理端（修复原产品洞 P1-1：匿名 Vue 管理台 + 弱口令 + 无审计）。

安全默认：
- 登录换 admin JWT（role 字段进 token；user 角色 403）；
- 登录失败统一 401（不区分账号不存在/密码错，防枚举）；
- 每个写动作落 admin_audit_log；
- 初始管理员密码从环境注入（SC_ADMIN_INITIAL_PASSWORD），空则不创建——
  没有默认口令，杜绝「admin/123456」式裸奔。
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
import csv
import io
from datetime import datetime, timezone

from ..models import (AdminAuditLog, AdminUser, Commission, Distributor,
                      DistributorTransfer, GenerationJob, PaymentOrder, Tenant,
                      TenantConfig, User, WritingOrder)
from ..security import make_token, verify_password
from ..reports import summary
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


# ---------------------------------------------------------------- 租户（白标）
@router.post("/tenants", status_code=201)
async def create_tenant(body: dict, db: AsyncSession = Depends(get_db),
                        admin: CurrentUser = Depends(admin_user)):
    """新建白标租户（域名唯一）。密钥配置不进 API，由 DBA 直接维护加密列。"""
    from .tenant import TenantConfigIn, TenantCreateIn

    data = TenantCreateIn(**body)
    exists = (await db.execute(select(Tenant).where(Tenant.domain == data.domain))).scalars().first()
    if exists is not None:
        raise HTTPException(409, "该域名已绑定租户")
    tenant = Tenant(name=data.name, domain=data.domain, plan=data.plan)
    db.add(tenant)
    await db.flush()
    db.add(TenantConfig(tenant_id=tenant.id))
    await _audit(db, admin, "tenant.create", {"tenant_id": tenant.id},
                 {"name": tenant.name, "domain": tenant.domain, "plan": tenant.plan})
    await db.commit()
    return {"id": tenant.id, "name": tenant.name, "domain": tenant.domain, "plan": tenant.plan}


@router.get("/tenants")
async def list_tenants(db: AsyncSession = Depends(get_db),
                       admin: CurrentUser = Depends(admin_user)):
    rows = (await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))).scalars().all()
    return [{"id": t.id, "name": t.name, "domain": t.domain, "plan": t.plan,
             "status": t.status, "balance_cents": t.balance_cents,
             "created_at": t.created_at.isoformat() if t.created_at else None} for t in rows]


@router.put("/tenants/{tenant_id}/config")
async def update_tenant_config(tenant_id: str, body: dict, db: AsyncSession = Depends(get_db),
                               admin: CurrentUser = Depends(admin_user)):
    from .tenant import TenantConfigIn

    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在")
    data = TenantConfigIn(**body)
    cfg = await db.get(TenantConfig, tenant_id)
    if cfg is None:
        cfg = TenantConfig(tenant_id=tenant_id)
        db.add(cfg)
    cfg.brand_color = data.brand_color
    cfg.logo_url = data.logo_url
    cfg.support_contact = data.support_contact
    await _audit(db, admin, "tenant.config.update", {"tenant_id": tenant_id},
                 {"brand_color": data.brand_color})
    await db.commit()
    return {"tenant_id": tenant_id, "brand_color": cfg.brand_color,
            "logo_url": cfg.logo_url, "support_contact": cfg.support_contact}


# ---------------------------------------------------------------- 分销代理
class DistributorIn(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    phone: str = Field(min_length=6, max_length=32)
    code: str = Field(min_length=2, max_length=32)
    rate_bps: int = Field(default=500, ge=0, le=5000)  # 万分比，0~50%
    tenant_id: str = Field(default="primary", max_length=64)


@router.post("/distributors", status_code=201)
async def create_distributor(body: DistributorIn, db: AsyncSession = Depends(get_db),
                             admin: CurrentUser = Depends(admin_user)):
    exists = (await db.execute(select(Distributor).where(Distributor.code == body.code))).scalars().first()
    if exists is not None:
        raise HTTPException(409, "推广码已存在")
    dist = Distributor(tenant_id=body.tenant_id, name=body.name, phone=body.phone,
                       code=body.code, rate_bps=body.rate_bps)
    db.add(dist)
    await db.flush()
    await _audit(db, admin, "distributor.create", {"distributor_id": dist.id},
                 {"code": dist.code, "rate_bps": dist.rate_bps})
    await db.commit()
    return {"id": dist.id, "code": dist.code, "rate_bps": dist.rate_bps}


@router.get("/distributors")
async def list_distributors(db: AsyncSession = Depends(get_db),
                            admin: CurrentUser = Depends(admin_user)):
    rows = (await db.execute(select(Distributor).order_by(Distributor.created_at.desc()))).scalars().all()
    return [{"id": d.id, "name": d.name, "phone": d.phone, "code": d.code,
             "rate_bps": d.rate_bps, "balance_cents": d.balance_cents, "status": d.status,
             "created_at": d.created_at.isoformat() if d.created_at else None} for d in rows]


@router.get("/commissions")
async def list_commissions(status: str | None = None, db: AsyncSession = Depends(get_db),
                           admin: CurrentUser = Depends(admin_user)):
    stmt = select(Commission).order_by(Commission.created_at.desc()).limit(300)
    if status:
        stmt = stmt.where(Commission.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return [{"id": c.id, "distributor_id": c.distributor_id, "order_id": c.order_id,
             "order_amount_cents": c.order_amount_cents, "rate_bps": c.rate_bps,
             "amount_cents": c.amount_cents, "status": c.status,
             "created_at": c.created_at.isoformat() if c.created_at else None} for c in rows]


@router.post("/commissions/{commission_id}/settle")
async def settle_commission(commission_id: str, db: AsyncSession = Depends(get_db),
                            admin: CurrentUser = Depends(admin_user)):
    """结算佣金：pending → settled，并计入代理可提现余额（append 记账，不改历史）。"""
    c = await db.get(Commission, commission_id)
    if c is None:
        raise HTTPException(404, "佣金记录不存在")
    if c.status != "pending":
        raise HTTPException(409, f"当前状态 {c.status} 不可结算")
    dist = await db.get(Distributor, c.distributor_id)
    c.status = "settled"
    c.settled_at = datetime.now(timezone.utc)
    if dist is not None:
        dist.balance_cents = int(dist.balance_cents or 0) + int(c.amount_cents)
    await _audit(db, admin, "commission.settle", {"commission_id": c.id},
                 {"amount_cents": c.amount_cents, "distributor_id": c.distributor_id})
    await db.commit()
    return {"id": c.id, "status": c.status, "amount_cents": c.amount_cents}


@router.get("/distributor-transfers")
async def list_dist_transfers(status: str | None = None, db: AsyncSession = Depends(get_db),
                              admin: CurrentUser = Depends(admin_user)):
    stmt = select(DistributorTransfer).order_by(DistributorTransfer.created_at.desc()).limit(300)
    if status:
        stmt = stmt.where(DistributorTransfer.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return [{"id": r.id, "distributor_id": r.distributor_id, "amount_cents": r.amount_cents,
             "status": r.status, "note": r.note,
             "created_at": r.created_at.isoformat() if r.created_at else None,
             "paid_at": r.paid_at.isoformat() if r.paid_at else None} for r in rows]


@router.post("/distributor-transfers/{transfer_id}/{action}")
async def audit_dist_transfer(transfer_id: str, action: str, db: AsyncSession = Depends(get_db),
                              admin: CurrentUser = Depends(admin_user)):
    """审核提现：action ∈ {pay, reject}。打款只登记状态，真实出款由财务线下执行。"""
    if action not in ("pay", "reject"):
        raise HTTPException(422, "action 必须是 pay 或 reject")
    row = await db.get(DistributorTransfer, transfer_id)
    if row is None:
        raise HTTPException(404, "提现申请不存在")
    if row.status != "requested":
        raise HTTPException(409, f"当前状态 {row.status} 不可审核")
    row.status = "paid" if action == "pay" else "rejected"
    if action == "pay":
        row.paid_at = datetime.now(timezone.utc)
    await _audit(db, admin, f"distributor.transfer.{action}", {"transfer_id": row.id},
                 {"amount_cents": row.amount_cents, "distributor_id": row.distributor_id})
    await db.commit()
    return {"id": row.id, "status": row.status}


# ---------------------------------------------------------------- CSV 导出（审计/对账）
_CSV_KINDS = {
    "orders": ("订单", ["id", "tenant_id", "owner_id", "title", "education", "word_count",
                       "price_cents", "status", "paid_at", "created_at"]),
    "payments": ("支付", ["id", "serial_no", "order_id", "amount_cents", "pay_method",
                         "status", "provider_ref", "created_at", "paid_at"]),
    "commissions": ("佣金", ["id", "distributor_id", "order_id", "order_amount_cents",
                            "rate_bps", "amount_cents", "status", "created_at", "settled_at"]),
    "audit": ("审计", ["id", "admin_id", "action", "created_at"]),
}


@router.get("/exports/{kind}.csv")
async def export_csv(kind: str, db: AsyncSession = Depends(get_db),
                     admin: CurrentUser = Depends(admin_user)):
    """对账/审计 CSV（UTF-8 BOM，Excel 直接打开不乱码）。"""
    if kind not in _CSV_KINDS:
        raise HTTPException(404, f"不支持的导出类型：{kind}")
    label, fields = _CSV_KINDS[kind]
    model = {"orders": WritingOrder, "payments": PaymentOrder,
             "commissions": Commission, "audit": AdminAuditLog}[kind]
    rows = (await db.execute(select(model).order_by(model.created_at.desc()).limit(5000))).scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(fields)
    for r in rows:
        vals = []
        for f in fields:
            v = getattr(r, f, None)
            vals.append(v.isoformat() if hasattr(v, "isoformat") and v else ("" if v is None else v))
        writer.writerow(vals)
    await _audit(db, admin, f"export.csv.{kind}", {"rows": len(rows)}, {})
    await db.commit()
    data = ("\ufeff" + buf.getvalue()).encode("utf-8")
    return Response(content=data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'})


@router.get("/reports/summary")
async def report_summary(days: int = 7, db: AsyncSession = Depends(get_db),
                         admin: CurrentUser = Depends(admin_user)):
    """运营日报（近 N 天）：收入、订单、任务、AI 用量。与定时推送共用 app.reports.summary。"""
    if not 1 <= days <= 90:
        raise HTTPException(422, "days 需在 1~90 之间")
    return await summary(db, days)
