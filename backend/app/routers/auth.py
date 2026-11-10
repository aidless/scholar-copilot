"""注册/登录。区别于原产品：注册即发 token 保留（便利性），密码哈希在服务端。

防枚举：登录失败统一 401 同文案（原产品错误态差分可枚举账号——逆向实测 P1）。
"""
import re
import uuid
from urllib.parse import quote
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import SmsCode, User, WechatScene
from ..ratelimit import rate_limit_login
from ..security import hash_password, make_token, verify_password, verify_sms_code
from ..sms import gen_code, hash_code, send_sms_code
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


@router.post("/register", response_model=TokenOut, dependencies=[Depends(rate_limit_login)])
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    if not re.fullmatch(r"1\d{10}", body.phone):
        raise HTTPException(422, "手机号格式不正确")
    await check_sms_code(db, body.phone, "register", body.check_code)
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


@router.post("/login", response_model=TokenOut, dependencies=[Depends(rate_limit_login)])
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


# ── 短信验证码（替代原产品静态盐 sign 方案） ─────────────────────────

class SmsSendIn(BaseModel):
    phone: str = Field(min_length=11, max_length=11)
    scene: str = Field(default="register", pattern="^(register|login)$")


@router.post("/sms/send", dependencies=[Depends(rate_limit_login)])
async def sms_send(body: SmsSendIn, db: AsyncSession = Depends(get_db)):
    """发送验证码。无论手机号是否已注册都返回同一响应（不给注册状态 oracle）。"""
    if not re.fullmatch(r"1\d{10}", body.phone):
        raise HTTPException(422, "手机号格式不正确")
    code = gen_code()
    now = datetime.now(timezone.utc)
    db.add(SmsCode(phone=body.phone, scene=body.scene, code_hash=hash_code(body.phone, body.scene, code),
                   expires_at=now + timedelta(seconds=settings.sms_code_ttl_seconds)))
    await db.commit()
    try:
        await send_sms_code(body.phone, body.scene, code)
    except RuntimeError as exc:
        raise HTTPException(502, f"短信发送失败：{exc}") from None
    out = {"sent": True, "expires_in": settings.sms_code_ttl_seconds}
    if settings.sms_dev_mode:  # dev 显式回显，便于本地调试；生产不返回
        out["dev_code"] = code
    return out


async def check_sms_code(db: AsyncSession, phone: str, scene: str, code: str) -> None:
    """校验验证码：dev 模式接受 000000（保留联调便利），否则查库比对摘要。"""
    if settings.sms_dev_mode and code == "000000":
        return
    row = (await db.execute(
        select(SmsCode).where(SmsCode.phone == phone, SmsCode.scene == scene,
                              SmsCode.consumed.is_(False))
        .order_by(SmsCode.created_at.desc())
    )).scalars().first()
    now = datetime.now(timezone.utc)
    if row is None or row.expires_at.replace(tzinfo=timezone.utc) < now or row.attempts >= 5:
        raise HTTPException(400, "验证码错误或已过期")
    row.attempts += 1
    if row.code_hash != hash_code(phone, scene, code):
        await db.commit()
        raise HTTPException(400, "验证码错误或已过期")
    row.consumed = True
    await db.commit()


# ── 微信扫码登录（dev 可 mock 确认；生产需配置 SC_WECHAT_APP_ID/SECRET） ────

@router.post("/wechat/qrcode")
async def wechat_qrcode(db: AsyncSession = Depends(get_db)):
    scene = uuid.uuid4().hex
    db.add(WechatScene(scene=scene))
    await db.commit()
    if not settings.wechat_app_id:
        if not settings.sms_dev_mode:
            raise HTTPException(503, "微信登录未配置（需 SC_WECHAT_APP_ID / SC_WECHAT_APP_SECRET）")
        return {"scene": scene, "mode": "dev", "qr_url": f"dev://wechat/{scene}",
                "poll_after_seconds": 2}
    redirect = settings.wechat_redirect_uri or ""
    return {"scene": scene, "mode": "wechat",
            "qr_url": f"https://open.weixin.qq.com/connect/qrconnect?appid={settings.wechat_app_id}"
                      f"&redirect_uri={quote(redirect, safe='')}"
                      f"&response_type=code&scope=snsapi_login&state={scene}#wechat_redirect",
            "poll_after_seconds": 2}


@router.post("/wechat/mock-approve")
async def wechat_mock_approve(body: dict, db: AsyncSession = Depends(get_db)):
    """dev-only：模拟扫码确认（生产环境一律 403）。"""
    if not settings.sms_dev_mode:
        raise HTTPException(403, "仅 dev 模式可用")
    scene = (body or {}).get("scene", "")
    phone = (body or {}).get("phone", "")
    if not re.fullmatch(r"1\d{10}", str(phone)):
        raise HTTPException(422, "手机号格式不正确")
    ws = (await db.execute(select(WechatScene).where(WechatScene.scene == scene))).scalars().first()
    if ws is None:
        raise HTTPException(404, "扫码会话不存在")
    user = (await db.execute(select(User).where(User.phone == phone))).scalars().first()
    if user is None:
        user = User(phone=phone, password_hash=hash_password(uuid.uuid4().hex), tenant_id="primary")
        db.add(user)
        await db.flush()
    ws.status = "confirmed"
    ws.user_id = user.id
    ws.confirmed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "confirmed"}


@router.get("/wechat/poll")
async def wechat_poll(scene: str, db: AsyncSession = Depends(get_db)):
    ws = (await db.execute(select(WechatScene).where(WechatScene.scene == scene))).scalars().first()
    if ws is None:
        raise HTTPException(404, "扫码会话不存在")
    if ws.status == "confirmed" and ws.user_id:
        user = await db.get(User, ws.user_id)
        return {"status": "confirmed", "access_token": make_token(user.id, user.tenant_id),
                "token_type": "bearer"}
    return {"status": ws.status}


# ── 微信真实回调网关（公众号/服务号「服务器配置」指向此处） ──────────────────
# GET：微信校验 URL，验签通过原样回 echostr。
# POST：微信推送事件（用户扫带参二维码 subscribe/SCAN），验签 + 解析 XML →
#       把对应 scene 标成 scanned 并记 openid；若该 openid 已绑定用户则直接 confirmed。

from fastapi import Request, Response  # noqa: E402
from .. import wechat as wx  # noqa: E402


def _wx_verify_or_403(signature: str, timestamp: str, nonce: str) -> None:
    """统一验签入口：Token 未配置或签名不符一律 403（不给探测者任何差分信息）。"""
    if not settings.wechat_token:
        raise HTTPException(503, "微信回调未配置（需 SC_WECHAT_TOKEN）")
    if not wx.verify_signature(settings.wechat_token, signature, timestamp, nonce):
        raise HTTPException(403, "签名校验失败")


@router.get("/wechat/callback")
async def wechat_callback_verify(
    signature: str = "", timestamp: str = "", nonce: str = "", echostr: str = ""
):
    """微信服务器 URL 校验握手：验签通过把 echostr 原样返回（纯文本）。"""
    _wx_verify_or_403(signature, timestamp, nonce)
    return Response(content=echostr, media_type="text/plain")


@router.post("/wechat/callback")
async def wechat_callback_event(
    request: Request,
    signature: str = "",
    timestamp: str = "",
    nonce: str = "",
    db: AsyncSession = Depends(get_db),
):
    """接收微信事件推送：解析 → 关联扫码会话。成功回 "success"（微信要求）。"""
    _wx_verify_or_403(signature, timestamp, nonce)
    body = await request.body()
    try:
        ev = wx.parse_event(body)
    except ValueError:
        raise HTTPException(400, "事件解析失败")

    # 只处理扫码相关事件：subscribe（未关注扫码）/ SCAN（已关注扫码）
    scene = wx.extract_scene(ev.get("event_key", ""))
    if ev.get("event") in ("subscribe", "SCAN") and scene:
        ws = (await db.execute(
            select(WechatScene).where(WechatScene.scene == scene)
        )).scalars().first()
        if ws is not None and ws.status == "pending":
            openid = ev.get("from_user", "")
            ws.openid = openid or ws.openid
            # 该 openid 已经绑定过用户 → 直接完成登录
            bound = (await db.execute(
                select(User).where(User.wechat_openid == openid)
            )).scalars().first() if openid else None
            if bound is not None:
                ws.status = "confirmed"
                ws.user_id = bound.id
                ws.confirmed_at = datetime.now(timezone.utc)
            else:
                ws.status = "scanned"  # 已扫，待前端走绑定手机号/或直接建号
            await db.commit()

    # 微信要求 5 秒内回 "success"（空串也行），否则重试
    return Response(content="success", media_type="text/plain")


@router.post("/wechat/complete")
async def wechat_complete(body: dict, db: AsyncSession = Depends(get_db)):
    """扫码后完成登录：用 openid 找到/创建用户并确认会话（真实网关下前端调用）。

    dev 模式亦可用来模拟真实回调后的绑定（与 mock-approve 的区别：这条走 openid）。
    """
    scene = (body or {}).get("scene", "")
    phone = (body or {}).get("phone", "")
    ws = (await db.execute(select(WechatScene).where(WechatScene.scene == scene))).scalars().first()
    if ws is None:
        raise HTTPException(404, "扫码会话不存在")
    if ws.status == "confirmed" and ws.user_id:
        user = await db.get(User, ws.user_id)
    else:
        if not re.fullmatch(r"1\d{10}", str(phone)):
            raise HTTPException(422, "手机号格式不正确")
        user = (await db.execute(select(User).where(User.phone == phone))).scalars().first()
        if user is None:
            user = User(phone=phone, password_hash=hash_password(uuid.uuid4().hex), tenant_id="primary")
            db.add(user)
            await db.flush()
        if ws.openid and not user.wechat_openid:
            user.wechat_openid = ws.openid
        ws.status = "confirmed"
        ws.user_id = user.id
        ws.confirmed_at = datetime.now(timezone.utc)
        await db.commit()
    return {"status": "confirmed", "access_token": make_token(user.id, user.tenant_id),
            "token_type": "bearer"}


@router.get("/wechat/oauth/callback")
async def wechat_oauth_callback(
    code: str = "", state: str = "", db: AsyncSession = Depends(get_db)
):
    """网站应用扫码登录回调：微信重定向到此处带 code+state(scene)。

    用 code 换 openid → 推进对应扫码会话（已绑定用户则直接 confirmed）。
    成功后返回一段极简 HTML（浏览器可关闭），真实登录态由前端 poll 拿 token。
    """
    if not settings.wechat_app_id or not settings.wechat_app_secret:
        raise HTTPException(503, "微信登录未配置（需 SC_WECHAT_APP_ID / SC_WECHAT_APP_SECRET）")
    if not code or not state:
        raise HTTPException(422, "缺少 code 或 state")
    ws = (await db.execute(
        select(WechatScene).where(WechatScene.scene == state)
    )).scalars().first()
    if ws is None:
        raise HTTPException(404, "扫码会话不存在")
    try:
        data = await wx.fetch_openid(code, settings.wechat_app_id, settings.wechat_app_secret)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from None
    openid = data["openid"]
    if ws.status == "pending":
        ws.openid = openid
        bound = (await db.execute(
            select(User).where(User.wechat_openid == openid)
        )).scalars().first()
        if bound is not None:
            ws.status = "confirmed"
            ws.user_id = bound.id
            ws.confirmed_at = datetime.now(timezone.utc)
        else:
            ws.status = "scanned"
        await db.commit()
    return Response(
        content="<html><body><h3>登录成功，请回到原窗口继续（可关闭本页）。</h3></body></html>",
        media_type="text/html",
    )
