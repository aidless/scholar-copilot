"""运营日报定时推送（arq cron）。

设计要点：
- 计算口径复用 `app.reports.summary`，与管理台 `/admin/reports/summary` 完全同源
  （两处各写一遍 SQL 迟早漂移，日报数字对不上是最难查的运维问题）。
- 默认关闭：`SC_REPORT_PUSH_ENABLED=false` 且 webhook 为空时不发任何请求，
  避免自部署用户莫名其妙被打外部接口。
- webhook 载荷同时给结构化 `data` 与纯文本 `text`：企业微信/飞书/Slack 机器人
  都能直接用，无需各自适配。
"""
import logging

import httpx

from ..config import settings

log = logging.getLogger(__name__)


async def push_daily_report(ctx=None) -> dict:
    """算一次日报并 POST 到 webhook。返回结构化结果，便于 arq 结果查询与测试断言。"""
    from ..db import _engine_and_session
    from ..reports import format_text, summary

    if not settings.report_push_enabled:
        return {"pushed": False, "reason": "disabled"}
    if not settings.report_webhook_url:
        return {"pushed": False, "reason": "no_webhook_url"}

    async with _engine_and_session()[1]() as db:
        data = await summary(db, settings.report_push_days)
    text = format_text(data)

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
        return {"pushed": ok, "status_code": r.status_code, "text": text}
    except Exception as exc:  # 推送失败不该让 cron 反复报错刷屏
        log.warning("日报推送异常：%s: %s", type(exc).__name__, exc)
        return {"pushed": False, "error": f"{type(exc).__name__}: {exc}"}
