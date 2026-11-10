"""运营日报定时推送：口径同源 + 默认不打扰 + 失败不刷屏。

为什么测这三件事：
1) **口径同源**——推送正文的数字必须与 `/admin/reports/summary` 完全一致。若两处各写
   一遍 SQL，日报与管理台对不上是最难查的运维问题，所以两边都走 `app.reports.summary`。
2) **默认不打扰**——`report_push_enabled=false` 或 webhook 为空时**不得发任何请求**
   （自部署用户不该被莫名打外部接口）。
3) **失败不刷屏**——webhook 500/连不上时返回 `pushed=false` 而非抛异常，
   否则 arq cron 会反复记错误日志。
"""
import pytest

from app.config import settings
from app.tasks import report as report_mod


class _FakeResp:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    """记录被 POST 的载荷，用于断言「发了什么」而不真打网络。"""

    sent: list = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        _FakeClient.sent.append({"url": url, "json": json})
        return _FakeClient.resp


@pytest.mark.anyio
async def test_disabled_does_not_send(monkeypatch):
    monkeypatch.setattr(settings, "report_push_enabled", False)
    monkeypatch.setattr(settings, "report_webhook_url", "http://example.invalid/hook")
    _FakeClient.sent = []
    monkeypatch.setattr(report_mod.httpx, "AsyncClient", _FakeClient)

    out = await report_mod.push_daily_report()
    assert out == {"pushed": False, "reason": "disabled"}
    assert _FakeClient.sent == [], "关闭时不得发任何请求"


@pytest.mark.anyio
async def test_missing_webhook_does_not_send(monkeypatch):
    monkeypatch.setattr(settings, "report_push_enabled", True)
    monkeypatch.setattr(settings, "report_webhook_url", "")
    _FakeClient.sent = []
    monkeypatch.setattr(report_mod.httpx, "AsyncClient", _FakeClient)

    out = await report_mod.push_daily_report()
    assert out == {"pushed": False, "reason": "no_webhook_url"}
    assert _FakeClient.sent == []


@pytest.mark.anyio
async def test_payload_matches_admin_report(monkeypatch):
    """推送正文的数字必须与管理台日报一致（同源口径）。"""
    monkeypatch.setattr(settings, "report_push_enabled", True)
    monkeypatch.setattr(settings, "report_webhook_url", "http://hook.invalid/x")
    monkeypatch.setattr(settings, "report_push_days", 7)
    _FakeClient.sent = []
    _FakeClient.resp = _FakeResp(200)
    monkeypatch.setattr(report_mod.httpx, "AsyncClient", _FakeClient)

    out = await report_mod.push_daily_report()
    assert out["pushed"] is True
    assert len(_FakeClient.sent) == 1
    payload = _FakeClient.sent[0]["json"]
    data = payload["data"]
    # 与管理台端点对比（同一 DB、同一窗口）
    from app.reports import summary as shared_summary
    from app.db import _engine_and_session

    async with _engine_and_session()[1]() as db:
        expected = await shared_summary(db, 7)
    assert data["revenue_cents"] == expected["revenue_cents"]
    assert data["orders_new"] == expected["orders_new"]
    assert data["new_users"] == expected["new_users"]
    assert data["tokens_in"] == expected["tokens_in"]
    # 纯文本与结构化同时给出（企业微信/飞书/Slack 都能直接用）
    content = payload["text"]["content"]
    assert "运营日报" in content
    assert payload["msgtype"] == "text"
    # 必须是真换行，不能是字面反斜杠 n（曾把 f-string 写成 \\\\n 导致 IM 里一行到底）
    assert "\\n" not in content
    assert content.count("\n") == 3


@pytest.mark.anyio
async def test_webhook_error_is_soft_failure(monkeypatch):
    monkeypatch.setattr(settings, "report_push_enabled", True)
    monkeypatch.setattr(settings, "report_webhook_url", "http://hook.invalid/x")
    _FakeClient.sent = []
    _FakeClient.resp = _FakeResp(500, "boom")
    monkeypatch.setattr(report_mod.httpx, "AsyncClient", _FakeClient)

    out = await report_mod.push_daily_report()
    assert out["pushed"] is False
    assert out["status_code"] == 500


@pytest.mark.anyio
async def test_webhook_exception_is_soft_failure(monkeypatch):
    monkeypatch.setattr(settings, "report_push_enabled", True)
    monkeypatch.setattr(settings, "report_webhook_url", "http://hook.invalid/x")

    class Boom:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            raise RuntimeError("network down")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(report_mod.httpx, "AsyncClient", Boom)
    out = await report_mod.push_daily_report()
    assert out["pushed"] is False
    assert "network down" in out["error"]


def test_cron_registered_only_when_enabled(monkeypatch):
    """默认部署不该凭空跑定时任务；开启后才注册 cron。"""
    from app.tasks import worker

    monkeypatch.setattr(settings, "report_push_enabled", False)
    assert worker._cron_jobs() == []

    monkeypatch.setattr(settings, "report_push_enabled", True)
    monkeypatch.setattr(settings, "report_push_hour", 9)
    jobs = worker._cron_jobs()
    assert len(jobs) == 1
    assert jobs[0].name == "daily_report"
    assert jobs[0].hour == 9
