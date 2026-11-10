"""最小冒烟：应用能构建、健康检查 200、版本号正确。"""
from fastapi.testclient import TestClient

from app.main import VERSION, create_app


def test_health():
    client = TestClient(create_app())
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["version"] == VERSION
