"""鉴权与签名原语。

安全默认（对照逆向报告的四个洞）：
- 密码 bcrypt（商业站是客户端 MD5 直传——两条都不够，但 bcrypt 至少拖慢离线爆破）
- JWT 7 天有效，payload 带 tenant_id + user_id
- 短信签名 HMAC-SHA256(now//300 + phone)，替代静态盐
"""
import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import settings


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    return bcrypt.checkpw(raw.encode(), hashed.encode())


def make_token(user_id: str, tenant_id: str, role: str = "user") -> str:
    payload = {
        "sub": user_id,
        "tid": tenant_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(days=settings.jwt_expire_days),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def parse_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def sms_signature(phone: str) -> str:
    """HMAC(时间窗 + 手机号)。客户端无需参与——MVP 里签名只由服务端生成，杜绝静态盐复算。"""
    window = str(int(time.time()) // 300)
    msg = f"{window}:{phone}".encode()
    return hmac.new(settings.sms_hmac_key.encode(), msg, hashlib.sha256).hexdigest()


def verify_sms_code(phone: str, code: str) -> bool:
    """校验短信验证码。

    开发模式（SC_SMS_DEV_MODE=true）：固定码 000000，方便本地联调与测试。
    生产模式：比对 HMAC 时间窗签名（当前窗 + 上一窗，容忍窗边界）。
    """
    if settings.sms_dev_mode:
        return code == "000000"
    window = int(time.time()) // 300
    for w in (window, window - 1):
        msg = f"{w}:{phone}".encode()
        expected = hmac.new(settings.sms_hmac_key.encode(), msg, hashlib.sha256).hexdigest()
        if hmac.compare_digest(code, expected):
            return True
    return False
