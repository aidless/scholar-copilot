"""短信网关抽象：dev（不发真短信）/ http（通用网关）。

纪律：
- 验证码随机生成、只存 SHA-256 摘要（app/models.py SmsCode），5 分钟过期、限尝试次数；
- 发送前不做「手机号是否注册」的分支判断——原产品正是靠这个差异泄露注册状态
  （正确 sign → 「未注册」，错误 sign → 「发送失败」，构成单向枚举 oracle）；
  本实现无论注册与否统一返回「验证码已发送」。
"""
import hashlib
import logging
import secrets

import httpx

from .config import settings

log = logging.getLogger(__name__)


def gen_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def hash_code(phone: str, scene: str, code: str) -> str:
    return hashlib.sha256(f"{phone}:{scene}:{code}".encode()).hexdigest()


async def send_sms_code(phone: str, scene: str, code: str) -> None:
    """向网关投递验证码。dev 只打日志；http 走 POST {phone, code, scene}。"""
    if settings.sms_provider == "dev":
        log.info("SMS(dev) to=%s scene=%s code=%s", phone, scene, code)
        return
    if settings.sms_provider != "http" or not settings.sms_api_url:
        raise RuntimeError("短信网关未配置（SC_SMS_PROVIDER=http 需同时配置 SC_SMS_API_URL）")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            settings.sms_api_url,
            json={"phone": phone, "code": code, "scene": scene},
            headers={"Authorization": f"Bearer {settings.sms_api_token}"} if settings.sms_api_token else {},
        )
        if resp.status_code >= 300:
            raise RuntimeError(f"短信网关返回 {resp.status_code}")
