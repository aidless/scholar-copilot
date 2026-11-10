"""写作全链：定价服务端算 / IDOR 404 / 配额 402 / 大纲→章节→改稿→导出。"""
from fastapi.testclient import TestClient

PHONE_A = "13800000010"
PHONE_B = "13800000011"
PW = "Test123456"


def make_client():
    from app.main import create_app
    return TestClient(create_app())


def register(client: TestClient, phone: str) -> str:
    r = client.post("/auth/register", json={"phone": phone, "password": PW, "check_code": "000000"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def pay_order(client: TestClient, token: str, order_id: str) -> None:
    """v0.5 起正文生成需支付解锁：mock 模式创建支付单并确认。"""
    r = client.post(f"/payments/orders/{order_id}",
                    json={"pay_method": "wechat"}, headers=auth(token))
    assert r.status_code == 200, r.text
    serial = r.json()["serial_no"]
    r = client.post(f"/payments/{serial}/confirm", headers=auth(token))
    assert r.status_code == 200, r.text


def create_order(client: TestClient, token: str, **over) -> dict:
    body = {"title": "基于大语言模型的学术写作助手研究", "education": "硕士",
            "word_count": 10000, **over}
    r = client.post("/writing/orders", json=body, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def test_create_order_price_server_side():
    """客户端传的 price_cents 被忽略；价格=0.04元/字×10000×100=40000分。"""
    with make_client() as client:
        token = register(client, PHONE_A)
        order = create_order(client, token, price_cents=1)
        assert order["price_cents"] == 40000
        assert order["status"] == "draft"


def test_order_idor_404():
    """A 的订单对 B：GET 404、list 空、DELETE 404——统一 404 防枚举。"""
    with make_client() as client:
        ta = register(client, PHONE_A)
        tb = register(client, PHONE_B)
        order = create_order(client, ta)

        r = client.get(f"/writing/orders/{order['id']}", headers=auth(tb))
        assert r.status_code == 404
        r = client.get("/writing/orders", headers=auth(tb))
        assert r.json() == []
        r = client.delete(f"/writing/orders/{order['id']}", headers=auth(tb))
        assert r.status_code == 404
        r = client.get(f"/writing/orders/{order['id']}", headers=auth(ta))
        assert r.status_code == 200


def test_outline_quota_server_enforced_402():
    """免费 3 次服务端强制：第 4 次 402；第二个用户不受影响（各自台账）。"""
    with make_client() as client:
        ta = register(client, PHONE_A)
        order = create_order(client, ta)
        for _ in range(3):
            r = client.post(f"/writing/orders/{order['id']}/outline?wait=true",
                            json={}, headers=auth(ta))
            assert r.status_code == 200, r.text
            assert r.json()["job"]["status"] == "done"
        r = client.post(f"/writing/orders/{order['id']}/outline?wait=true",
                        json={}, headers=auth(ta))
        assert r.status_code == 402

        # quota 端点读数一致
        r = client.get("/billing/quota", headers=auth(ta))
        assert r.json()["used"] == 3 and r.json()["remaining"] == 0

        # 另一个用户仍有自己的 3 次
        tb = register(client, PHONE_B)
        order_b = create_order(client, tb)
        r = client.post(f"/writing/orders/{order_b['id']}/outline?wait=true",
                        json={}, headers=auth(tb))
        assert r.status_code == 200


def test_outline_creates_chapter_skeleton():
    with make_client() as client:
        token = register(client, PHONE_A)
        order = create_order(client, token)
        r = client.post(f"/writing/orders/{order['id']}/outline?wait=true",
                        json={}, headers=auth(token))
        assert r.status_code == 200
        assert r.json()["order"]["status"] == "outline_done"

        # 大纲内容可读，版本 1
        r = client.get(f"/writing/orders/{order['id']}/outline", headers=auth(token))
        assert r.status_code == 200
        assert r.json()["version"] == 1
        assert "## 第一章" in r.json()["content_md"]

        # fake 大纲 = 5 章 level1 骨架
        r = client.get(f"/writing/orders/{order['id']}/chapters", headers=auth(token))
        chapters = r.json()
        assert [c["node_id"] for c in chapters] == ["ch1", "ch2", "ch3", "ch4", "ch5"]
        assert all(c["status"] == "pending" for c in chapters)
        assert all(c["ai_level"] == "C" for c in chapters)


def test_full_chain_chapters_edit_export():
    """大纲→支付→逐章生成→改稿(A→B)→全完成→导出 DOCX。"""
    with make_client() as client:
        token = register(client, PHONE_A)
        order = create_order(client, token)
        client.post(f"/writing/orders/{order['id']}/outline?wait=true", json={}, headers=auth(token))
        pay_order(client, token, order["id"])

        # 逐章生成
        for node in ["ch1", "ch2", "ch3", "ch4", "ch5"]:
            r = client.post(f"/writing/orders/{order['id']}/chapters/{node}?wait=true",
                            json=None, headers=auth(token))
            assert r.status_code == 200, r.text
            ch = r.json()["chapter"]
            assert ch["status"] == "done"
            assert ch["ai_level"] == "A"  # 生成即 AI 未修改
            assert ch["word_count"] > 0

        r = client.get(f"/writing/orders/{order['id']}", headers=auth(token))
        assert r.json()["status"] == "writing_done"

        # 改稿：A → 自动升 B（如实披露）
        r = client.put(f"/writing/orders/{order['id']}/chapters/ch1",
                       json={"content_md": "# 人工修改后的内容\n\n这一段由用户亲手改写。"},
                       headers=auth(token))
        assert r.status_code == 200
        assert r.json()["ai_level"] == "B"

        # 导出
        r = client.post(f"/writing/orders/{order['id']}/export", headers=auth(token))
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        assert r.content[:2] == b"PK"  # zip 魔数（docx 即 zip）
        assert len(r.content) > 10000

        # 导出后状态
        r = client.get(f"/writing/orders/{order['id']}", headers=auth(token))
        assert r.json()["status"] == "exported"


def test_export_blocked_until_all_chapters_done():
    with make_client() as client:
        token = register(client, PHONE_A)
        order = create_order(client, token)
        r = client.post(f"/writing/orders/{order['id']}/export", headers=auth(token))
        assert r.status_code == 409  # 没有大纲/章节

        client.post(f"/writing/orders/{order['id']}/outline?wait=true", json={}, headers=auth(token))
        pay_order(client, token, order["id"])
        r = client.post(f"/writing/orders/{order['id']}/chapters/ch1?wait=true",
                        json=None, headers=auth(token))
        assert r.status_code == 200
        r = client.post(f"/writing/orders/{order['id']}/export", headers=auth(token))
        assert r.status_code == 409  # 还有 4 章未完成
        assert "4" in r.json()["detail"]


def test_job_polling_ownership():
    with make_client() as client:
        ta = register(client, PHONE_A)
        tb = register(client, PHONE_B)
        order = create_order(client, ta)
        r = client.post(f"/writing/orders/{order['id']}/outline?wait=false",
                        json={}, headers=auth(ta))
        assert r.status_code == 200
        job_id = r.json()["job_id"]
        # B 查 A 的 job → 404
        assert client.get(f"/jobs/{job_id}", headers=auth(tb)).status_code == 404
        # A 自己可查（wait=false 后台任务最终 done）
        import time
        deadline = time.time() + 10
        status = None
        while time.time() < deadline:
            r = client.get(f"/jobs/{job_id}", headers=auth(ta))
            status = r.json()["status"]
            if status == "done":
                break
            time.sleep(0.2)
        assert status == "done"
