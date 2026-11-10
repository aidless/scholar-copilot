"""注册/登录。区别于原产品：注册即发 token 保留（便利性），密码哈希在服务端。

防枚举：登录失败统一 401 同文案（原产品错误态差分可枚举账号——逆向实测 P1）。
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import User
from ..security import hash_password, make_token, verify_password, verify_sms_code
from ..tenancy import CurrentUser, current_user
from ..writing.service import quota_remaining

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    phone: str = Field(min_length=11, max_length=11)
    password: str = Field(min_length=8, max_length=64)
    check_code: str = Field(min_length=1, max_length=16)


class LoginIn(BaseModel):
    phone: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=TokenOut)
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    if not re.fullmatch(r"1\d{10}", body.phone):
        raise HTTPException(422, "手机号格式不正确")
    if not verify_sms_code(body.phone, body.check_code):
        raise HTTPException(400, "验证码错误或已过期")
    exists = (await db.execute(
        select(User).where(User.phone == body.phone)
    )).scalar()
    if exists is not None:
        raise HTTPException(409, "注册失败：该手机号已被使用")
    user = User(
        phone=body.phone,
        password_hash=hash_password(body.password),
        tenant_id="primary",
    )
    db.add(user)
    await db.commit()
    return TokenOut(access_token=make_token(user.id, user.tenant_id))


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(
        select(User).where(User.phone == body.phone)
    )).scalar()
    # 统一 401 同文案：不泄露「号存在但密码错」
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "手机号或密码错误")
    return TokenOut(access_token=make_token(user.id, user.tenant_id))


@router.get("/me")
async def me(user: CurrentUser = Depends(current_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(User, user.user_id)
    if row is None:
        raise HTTPException(401, "登录态失效")
    remaining = await quota_remaining(db, user.user_id)
    return {
        "user_id": row.id,
        "phone": row.phone,
        "tenant_id": row.tenant_id,
        "quota": {
            "kind": "outline",
            "limit": settings.free_outline_limit,
            "remaining": remaining,
        },
    }
