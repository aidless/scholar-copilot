"""初始管理员引导与 schema 建表方式解耦（compose 用 alembic 建表时必须仍能登录管理台）。

背景（2026-11-10 实测）：`bootstrap superadmin` 原先写在 `if settings.db_auto_create:`
分支内。compose 改成「alembic upgrade head 建表 + SC_DB_AUTO_CREATE=false」后，
表存在但管理员永远不被创建 → 管理台 `/admin/login` 全 401，演示链路断在这里。
"""
import pytest
from fastapi.testclient import TestClient

from app.config import settings


@pytest.fixture
def no_autocreate(monkeypatch):
    """模拟 compose 部署形态：表已由迁移建好，db_auto_create=False。"""
    monkeypatch.setattr(settings, "db_auto_create", False)
    monkeypatch.setattr(settings, "admin_initial_password", "bootstrap-pass-123")
    monkeypatch.setattr(settings, "admin_initial_login", "admin")
    return settings


def test_admin_bootstrapped_without_db_auto_create(no_autocreate):
    from app.main import create_app

    with TestClient(create_app()) as client:
        r = client.post(
            "/admin/login",
            json={"username": "admin", "password": "bootstrap-pass-123"},
        )
        assert r.status_code == 200, r.text
        assert r.json().get("access_token")


def test_admin_bootstrap_is_idempotent(no_autocreate):
    """重复启动不应插入第二条管理员（也不应 409/500）。"""
    from app.main import create_app

    for _ in range(2):
        with TestClient(create_app()) as client:
            r = client.post(
                "/admin/login",
                json={"username": "admin", "password": "bootstrap-pass-123"},
            )
            assert r.status_code == 200, r.text


def test_no_admin_created_when_password_empty(monkeypatch):
    """密码为空时不建账号（无默认口令）。"""
    monkeypatch.setattr(settings, "db_auto_create", False)
    monkeypatch.setattr(settings, "admin_initial_password", "")

    from app.main import create_app

    with TestClient(create_app()) as client:
        r = client.post("/admin/login", json={"username": "admin", "password": ""})
        assert r.status_code in (401, 422), r.text
