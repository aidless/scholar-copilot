"""运营日报定时推送（arq cron）。

设计要点：
- 计算口径复用 `app.reports.summary`，与管理台 `/admin/reports/summary` 完全同源
  （两处各写一遍 SQL 迟早漂移，日报数字对不上是最难查的运维问题）。
- 默认关闭：`SC_REPORT_PUSH_ENABLED=false` 时不发任何请求，避免自部署用户
  莫名其妙被打外部接口。
- 两个通道，二选一（v1.7 起）：`report_webhook_url` 非空 → POST webhook；
  否则 `report_email_to` 非空 → SMTP 发邮件；都为空 → 不发并说明原因。
- webhook 载荷同时给结构化 `data` 与纯文本 `text`：企业微信/飞书/Slack 机器人
  都能直接用，无需各自适配。
- 失败一律软返回（`pushed=false` + 原因），不让 arq cron 反复抛异常刷日志。
"""
import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

import httpx

from ..config import settings

log = logging.getLogger(__name__)


def _chosen_channel() -> str:
    """决定这次用哪个通道：webhook 优先，其次 email，都没有则 none。"""
    if settings.report_webhook_url:
        return "webhook"
    if settings.report_email_to:
        return "email"
    return "none"


def _build_email(text: str) -> EmailMessage:
    """把日报正文包成一封纯文本邮件。收件人逗号分隔，逐条加进 To。"""
    msg = EmailMessage()
    msg["Subject"] = "Scholar Copilot 运营日报"
    sender = settings.smtp_from or settings.smtp_user
    msg["From"] = formataddr(("Scholar Copilot", sender))
    msg["To"] = settings.report_email_to
    msg.set_content(text)
    return msg


def _send_email_sync(text: str) -> int:
    """阻塞式发信（在 to_thread 里跑，不阻塞事件循环）。返回收件人数。"""
    host = settings.smtp_host
    if not host:
        raise RuntimeError("SC_SMTP_HOST 未配置")
    recipients = [x.strip() for x in settings.report_email_to.split(",") if x.strip()]
    if not recipients:
        raise RuntimeError("SC_REPORT_EMAIL_TO 为空")
    msg = _build_email(text)
    if settings.smtp_ssl:
        server = smtplib.SMTP_SSL(host, settings.smtp_port, timeout=20)
    else:
        server = smtplib.SMTP(host, settings.smtp_port, timeout=20)
    try:
        if settings.smtp_starttls and not settings.smtp_ssl:
            server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg, from_addr=(settings.smtp_from or settings.smtp_user))
    finally:
        try:
            server.quit()
        except Exception:  # 退出异常不该盖住发送结果
            pass
    return len(recipients)


async def push_daily_report(ctx=None) -> dict:
    """算一次日报并按配置的通道推送。返回结构化结果，便于 arq 结果查询与测试断言。"""
    from ..db import _engine_and_session
    from ..reports import format_text, summary

    if not settings.report_push_enabled:
        return {"pushed": False, "reason": "disabled"}

    channel = _chosen_channel()
    if channel == "none":
        return {"pushed": False, "reason": "no_channel_configured"}

    async with _engine_and_session()[1]() as db:
        data = await summary(db, settings.report_push_days)
    text = format_text(data)

    if channel == "email":
        import asyncio

        try:
            n = await asyncio.to_thread(_send_email_sync, text)
            return {"pushed": True, "channel": "email", "recipients": n, "text": text}
        except Exception as exc:  # 发信失败软返回
            log.warning("日报邮件发送异常：%s: %s", type(exc).__name__, exc)
            return {"pushed": False, "channel": "email", "error": f"{type(exc).__name__}: {exc}"}

    payload = {
        "msgtype": "text",
        "text": {"content": text},
        "data": data,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(settings.report_webhook_url, json=payload)
        ok = 200 <= r.status_code < 300
        if not ok:
            log.warning("日报推送失败：HTTP %s %s", r.status_code, r.text[:200])
        return {"pushed": ok, "channel": "webhook", "status_code": r.status_code, "text": text}
    except Exception as exc:  # 推送失败不该让 cron 反复报错刷屏
        log.warning("日报推送异常：%s: %s", type(exc).__name__, exc)
        return {"pushed": False, "channel": "webhook", "error": f"{type(exc).__name__}: {exc}"}
