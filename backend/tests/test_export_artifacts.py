"""v1.12 #14：导出产物落对象存储 + 签名 URL。

此前导出都是「内存里拼好直接吐给浏览器」，关掉页面就没了，也没法给别人下载。
这里补：导出即归档（本地磁盘或 S3），并给一个有时效的签名链接。
"""
import hashlib
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

PHONE = "13620000001"
PW = "Test123456"


@contextmanager
def make_client():
    from app.main import create_app
    with TestClient(create_app()) as client:
        yield client


def register(client):
    r = client.post("/auth/register",
                    json={"phone": PHONE, "password": PW, "check_code": "000000"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def ready_order(client, token):
    """建单 → 大纲 → 支付 → 逐章完成，返回 order_id。"""
    order = client.post("/writing/orders",
                        json={"title": "导出归档测试", "education": "本科",
                              "word_count": 4000},
                        headers=auth(token)).json()
    client.post(f"/writing/orders/{order['id']}/outline?wait=true", json={},
                headers=auth(token))
    pay = client.post(f"/payments/orders/{order['id']}", json={"pay_method": "alipay"},
                      headers=auth(token)).json()
    client.post(f"/payments/{pay['serial_no']}/confirm", headers=auth(token))
    chapters = client.get(f"/writing/orders/{order['id']}/chapters",
                          headers=auth(token)).json()
    for ch in chapters:
        client.post(f"/writing/orders/{order['id']}/chapters/{ch['node_id']}?wait=true",
                    json={}, headers=auth(token))
    return order["id"]


def test_export_archives_artifact_and_signed_url():
    with make_client() as client:
        token = register(client)
        oid = ready_order(client, token)

        r = client.post(f"/writing/orders/{oid}/export", headers=auth(token))
        assert r.status_code == 200, r.text
        export_id = r.headers.get("X-Export-Id")
        assert export_id, "导出响应应带 X-Export-Id"
        digest = hashlib.sha256(r.content).hexdigest()

        # 归档列表
        r2 = client.get(f"/writing/orders/{oid}/exports", headers=auth(token))
        assert r2.status_code == 200, r2.text
        items = r2.json()["exports"]
        assert len(items) == 1
        art = items[0]
        assert art["id"] == export_id
        assert art["fmt"] == "docx"
        assert art["size"] == len(r.content)
        assert art["sha256"] == digest

        # 签名 URL（本地存储返回可下载路径 + 过期秒数）
        r3 = client.get(f"/writing/exports/{export_id}/signed-url", headers=auth(token))
        assert r3.status_code == 200, r3.text
        body = r3.json()
        assert body["url"]
        assert body["expires_in"] > 0

        # 直接下载，字节与首次导出一致（归档没损坏）
        r4 = client.get(f"/writing/exports/{export_id}/download", headers=auth(token))
        assert r4.status_code == 200
        assert hashlib.sha256(r4.content).hexdigest() == digest
        assert r4.headers["content-type"].startswith(
            "application/vnd.openxmlformats")


def test_export_artifact_is_owner_scoped():
    with make_client() as client:
        t1 = register(client)
        oid = ready_order(client, t1)
        export_id = client.post(f"/writing/orders/{oid}/export",
                                headers=auth(t1)).headers["X-Export-Id"]

        r = client.post("/auth/register",
                        json={"phone": "13620000002", "password": PW,
                              "check_code": "000000"})
        t2 = r.json()["access_token"]
        assert client.get(f"/writing/exports/{export_id}/signed-url",
                          headers=auth(t2)).status_code == 404
        assert client.get(f"/writing/exports/{export_id}/download",
                          headers=auth(t2)).status_code == 404
        assert client.get(f"/writing/orders/{oid}/exports",
                          headers=auth(t2)).status_code == 404


def test_export_history_grows_and_is_newest_first():
    with make_client() as client:
        token = register(client)
        oid = ready_order(client, token)
        first = client.post(f"/writing/orders/{oid}/export",
                            headers=auth(token)).headers["X-Export-Id"]
        second = client.post(f"/writing/orders/{oid}/export",
                             headers=auth(token)).headers["X-Export-Id"]
        assert first != second
        items = client.get(f"/writing/orders/{oid}/exports",
                           headers=auth(token)).json()["exports"]
        assert len(items) == 2
        assert items[0]["id"] == second  # 倒序：最新在前


def test_unknown_export_404():
    with make_client() as client:
        token = register(client)
        assert client.get("/writing/exports/nope/signed-url",
                          headers=auth(token)).status_code == 404
