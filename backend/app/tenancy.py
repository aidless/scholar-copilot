"""租户路由与属主校验——本项目最重要的两个安全依赖。

逆向教训：原产品 orderInfo 只验「是否登录」，不验属主/租户，任何登录用户可读任意租户订单。
这里的两个 FastAPI 依赖把「属主 + 租户」做成所有资源路由的强制参数，漏写就是类型错误。
"""
import time
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import parse_token


@dataclass
class CurrentUser:
    user_id: str
    tenant_id: str
    role: str = "user"


async def current_user(
    request: Request,
    authorization: str = Header(default=""),
) -> CurrentUser:
    """Bearer token 解析。匿名路由不要挂这个依赖，而不是在依赖里放行。"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "未登录")
    payload = parse_token(authorization.removeprefix("Bearer "))
    if payload is None:
        raise HTTPException(401, "登录已过期")
    return CurrentUser(user_id=payload["sub"], tenant_id=payload["tid"],
                       role=payload.get("role", "user"))


async def admin_user(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """管理端依赖：token role 必须是管理员角色（user 角色一律 403）。"""
    if user.role not in ("superadmin", "tenant_admin", "operator"):
        raise HTTPException(403, "需要管理员权限")
    return user


_HOST_CACHE: dict[str, tuple[float, str]] = {}
_HOST_TTL = 60.0


async def resolve_tenant(host: str, db: AsyncSession) -> str:
    """Host → tenant_id：查 tenants.domain（含端口/子域），未命中回退 "primary"。

    60 秒进程内缓存（白标域名不常变）；命中失败也缓存，避免每请求打库。
    """
    key = (host or "").lower()
    hit = _HOST_CACHE.get(key)
    if hit and time.time() - hit[0] < _HOST_TTL:
        return hit[1]
    from .models import Tenant  # 延迟导入避免循环

    candidates = [key]
    if ":" in key:
        candidates.append(key.split(":")[0])
    row = None
    if key:
        row = (await db.execute(
            select(Tenant).where(Tenant.domain.in_(candidates), Tenant.status == "active")
        )).scalars().first()
    tenant_id = row.id if row else "primary"
    _HOST_CACHE[key] = (time.time(), tenant_id)
    return tenant_id


async def tenant_scope(request: Request, db: AsyncSession = Depends(get_db)) -> str:
    """按 Host 头解析租户（多租户白标路由入口）。"""
    return await resolve_tenant(request.headers.get("host", ""), db)


async def distributor_user(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """分销代理端依赖：token role 必须是 distributor。"""
    if user.role != "distributor":
        raise HTTPException(403, "需要代理权限")
    return user


def ownership_filter(query, model, user: CurrentUser):
    """把 tenant_id + owner_id 双条件拼进任何 ORM 查询——IDOR 的结构性修复。

    用法：stmt = ownership_filter(select(WritingOrder), WritingOrder, user)
    """
    return query.where(
        model.tenant_id == user.tenant_id,
        model.owner_id == user.user_id,
    )


# 依赖组合导出，路由里写 Dependencies=[Depends(get_db), Depends(current_user)] 即可
AuthDeps = [Depends(get_db), Depends(current_user)]
