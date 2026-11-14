"""v0.5：支付订单（mock 模式）+ 多租户管理端 RBAC + 审计。"""
from fastapi.testclient import TestClient

PHONE_A = "13800000011"
PHONE_B = "13800000012"
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


def paid_order(client: TestClient, token: str, title: str = "支付测试订单") -> str:
    order = client.post("/writing/orders",
                        json={"title": title, "education": "本科", "word_count": 6000},
                        headers=auth(token)).json()
    client.post(f"/writing/orders/{order['id']}/outline?wait=true", json={}, headers=auth(token))
    r = client.post(f"/payments/orders/{order['id']}",
                    json={"pay_method": "wechat"}, headers=auth(token))
    assert r.status_code == 200, r.text
    return order["id"], r.json()


# ── 支付订单 ─────────────────────────────────────────────────

def test_payment_flow_gates_chapter_generation():
    """未支付→正文 402；创建支付单（服务端价）→confirm→正文解锁；重复操作 409。"""
    with make_client() as client:
        token = register(client, PHONE_A)
        order_id, pay = paid_order(client, token)

        assert pay["serial_no"].startswith("SC")
        assert pay["amount_cents"] == 6000 * 3  # 服务端价 0.03 元/字 = 3 分/字，与 /billing/quote 同源
        assert "amount" not in (pay.keys())  # 客户端无法传金额

        # 未支付：正文生成被 402 拦住（大纲免费，上文已成功）
        r = client.post(f"/writing/orders/{order_id}/chapters/ch1?wait=true",
                        json=None, headers=auth(token))
        assert r.status_code == 402
        assert "尚未支付" in r.json()["detail"]

        # 确认支付 → 解锁
        r = client.post(f"/payments/{pay['serial_no']}/confirm", headers=auth(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "paid"
        assert body["provider_ref"] == f"mock-{pay['serial_no']}"
        assert body["order_paid"] is True

        r = client.post(f"/writing/orders/{order_id}/chapters/ch1?wait=true",
                        json=None, headers=auth(token))
        assert r.status_code == 200

        # 重复创建支付单 / 重复确认 → 409
        r = client.post(f"/payments/orders/{order_id}",
                        json={"pay_method": "alipay"}, headers=auth(token))
        assert r.status_code == 409
        r = client.post(f"/payments/{pay['serial_no']}/confirm", headers=auth(token))
        assert r.status_code == 409


def test_payment_ownership():
    """别人的支付单：查询/确认一律 404（防枚举）；本人列表可见。"""
    with make_client() as client:
        ta = register(client, PHONE_A)
        tb = register(client, PHONE_B)
        _, pay = paid_order(client, ta)

        assert client.get(f"/payments/{pay['serial_no']}", headers=auth(tb)).status_code == 404
        assert client.post(f"/payments/{pay['serial_no']}/confirm",
                           headers=auth(tb)).status_code == 404

        rows = client.get("/payments", headers=auth(ta)).json()
        assert len(rows) == 1 and rows[0]["serial_no"] == pay["serial_no"]
        assert client.get("/payments", headers=auth(tb)).json() == []


# ── 管理端 ───────────────────────────────────────────────────

def admin_token(client: TestClient) -> str:
    from app.config import settings
    r = client.post("/admin/login",
                    json={"username": settings.admin_initial_login,
                          "password": settings.admin_initial_password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_admin_login_and_rbac():
    with make_client() as client:
        from app.config import settings

        # 用户 token 调管理端 → 403
        user_tok = register(client, PHONE_A)
        assert client.get("/admin/stats", headers=auth(user_tok)).status_code == 403
        # 无 token → 401
        assert client.get("/admin/stats").status_code == 401

        # 登录：正确密码 → superadmin；错密码 → 统一 401（防枚举）
        tok = admin_token(client)
        r = client.post("/admin/login",
                        json={"username": settings.admin_initial_login,
                              "password": "wrong-password-123"})
        assert r.status_code == 401
        r = client.post("/admin/login",
                        json={"username": settings.admin_initial_login,
                              "password": "wrong-password-123"})
        assert r.status_code == 401
        assert r.json()["detail"] == "用户名或密码错误"

        r = client.get("/admin/stats", headers=auth(tok))
        assert r.status_code == 200
        stats = r.json()
        assert stats["users"] == 1 and stats["orders"] == 0


def test_admin_quota_adjust_and_audit():
    with make_client() as client:
        tok = admin_token(client)
        user_tok = register(client, PHONE_A)

        before = client.get("/auth/me", headers=auth(user_tok)).json()
        base_remaining = before["quota"]["remaining"]

        # 赠 2 次
        r = client.post("/admin/quota/adjust", headers=auth(tok),
                        json={"user_id": before["user_id"], "kind": "outline",
                              "delta": 2, "reason": "测试赠送"})
        assert r.status_code == 200, r.text
        after = client.get("/auth/me", headers=auth(user_tok)).json()
        assert after["quota"]["remaining"] == base_remaining + 2

        # 回收 1 次（负 delta）
        client.post("/admin/quota/adjust", headers=auth(tok),
                    json={"user_id": before["user_id"], "kind": "outline",
                          "delta": -1, "reason": "测试回收"})
        after2 = client.get("/auth/me", headers=auth(user_tok)).json()
        assert after2["quota"]["remaining"] == base_remaining + 1

        # 不存在的用户 404；用户 token 调整 403
        assert client.post("/admin/quota/adjust", headers=auth(tok),
                           json={"user_id": "no-such-user", "kind": "outline",
                                 "delta": 1, "reason": "不存在用户 probe"}).status_code == 404
        assert client.post("/admin/quota/adjust", headers=auth(user_tok),
                           json={"user_id": before["user_id"], "kind": "outline",
                                 "delta": 99, "reason": "自助提额"}).status_code == 403

        # 审计留痕：两次调整都有记录
        logs = client.get("/admin/audit-log", headers=auth(tok)).json()
        actions = [l["action"] for l in logs]
        assert actions.count("quota.adjust") == 2
        assert logs[0]["target"]["user_id"] == before["user_id"]


def test_admin_lists_orders_and_payments():
    with make_client() as client:
        tok = admin_token(client)
        ta = register(client, PHONE_A)
        order_id, pay = paid_order(client, ta, title="管理端可见订单")
        client.post(f"/payments/{pay['serial_no']}/confirm", headers=auth(ta))

        orders = client.get("/admin/orders", headers=auth(tok)).json()
        assert len(orders) == 1 and orders[0]["id"] == order_id
        assert orders[0]["paid_at"] is not None

        pays = client.get("/admin/payments", headers=auth(tok)).json()
        assert len(pays) == 1 and pays[0]["status"] == "paid"

        stats = client.get("/admin/stats", headers=auth(tok)).json()
        assert stats["payments_paid"] == 1
        assert stats["revenue_cents"] == pay["amount_cents"]

        # 按 tenant 过滤
        assert client.get("/admin/orders?tenant=no-such-tenant",
                          headers=auth(tok)).json() == []
