"""配额与定价：价格公式开源（原产品是服务端黑盒算价）。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
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
