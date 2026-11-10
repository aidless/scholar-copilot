"""白标租户对外接口：只暴露 branding（名称/配色/Logo/客服），绝不返回任何密钥字段。

对应原产品的 websiteInfo 漏洞：它把 wxAppSecret / kaifaToken / encodingAesKey 等
全量配置吐给匿名请求方。这里接口形状一样是「按域名查」，但返回白名单字段。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..tenancy import tenant_scope

router = APIRouter(prefix="/tenant", tags=["tenant"])

_BRANDING_FIELDS = ("tenant_id", "name", "domain", "plan", "brand_color", "logo_url", "support_contact")


@router.get("/branding")
async def branding(db: AsyncSession = Depends(get_db), tenant_id: str = Depends(tenant_scope)):
    """按 Host 解析租户并返回品牌信息（公开接口，字段白名单）。"""
    from ..models import Tenant, TenantConfig

    if tenant_id == "primary":
        return {"tenant_id": "primary", "name": "Scholar Copilot", "domain": None,
                "plan": "free", "brand_color": "#111827", "logo_url": None,
                "support_contact": None}

    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在")
    cfg = await db.get(TenantConfig, tenant_id)
    out = {
        "tenant_id": tenant.id,
        "name": tenant.name,
        "domain": tenant.domain,
        "plan": tenant.plan,
        "brand_color": cfg.brand_color if cfg else "#111827",
        "logo_url": cfg.logo_url if cfg else None,
        "support_contact": cfg.support_contact if cfg else None,
    }
    return {k: out[k] for k in _BRANDING_FIELDS}


class TenantCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    domain: str = Field(min_length=3, max_length=255)
    plan: str = Field(default="free", pattern="^(free|pro|enterprise)$")


class TenantConfigIn(BaseModel):
    brand_color: str = Field(default="#111827", pattern="^#[0-9a-fA-F]{6}$")
    logo_url: str | None = Field(default=None, max_length=255)
    support_contact: str | None = Field(default=None, max_length=128)
