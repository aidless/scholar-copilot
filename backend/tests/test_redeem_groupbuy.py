"""v1.12 #17：兑换码 + 拼团。

原产品有 exchangeCode 与 startGroupBuying 两条获客路径，我们只有「直接付全款」。
这里补：
- 兑换码：管理员批量生成 → 用户兑换成余额；一码一用，重复兑换 409。
- 拼团：开团（拼团价 + 人数下限）→ 凑满人数自动结算扣款并升级套餐；
  未凑满到期作废（演示里用 expires_in_minutes 参数，方便测试）。
"""
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

PHONE_A = "13910000001"
PHONE_B = "13910000002"
PHONE_C = "13910000003"
PW = "Test123456"
ADMIN_PW = "Adm-redeem-918"


@contextmanager
def make_client(admin_pw=ADMIN_PW):
    """临时注入初始管理员口令：bootstrap 在 lifespan 里跑，必须撑到 with 结束。"""
    from app.config import settings
    from app.main import create_app
    old = settings.admin_initial_password
    settings.admin_initial_password = admin_pw
    try:
        with TestClient(create_app()) as client:
            yield client
    finally:
        settings.admin_initial_password = old


def register(client, phone):
    r = client.post("/auth/register",
                    json={"phone": phone, "password": PW, "check_code": "000000"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def admin_token(client):
    r = client.post("/admin/login", json={"username": "admin", "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# ── 兑换码 ─────────────────────────────────────────────────

def test_admin_creates_redeem_codes():
    with make_client() as client:
        at = admin_token(client)
        r = client.post("/admin/redeem-codes", headers=auth(at),
                        json={"batch": "双十一", "amount_cents": 5000, "count": 3})
        assert r.status_code == 201, r.text
        body = r.json()
        assert len(body["codes"]) == 3
        assert len(set(body["codes"])) == 3  # 不重复
        assert all(len(c) >= 10 for c in body["codes"])

        r = client.get("/admin/redeem-codes?batch=双十一", headers=auth(at))
        assert r.status_code == 200
        rows = r.json()["codes"]
        assert len(rows) == 3
        assert all(row["amount_cents"] == 5000 for row in rows)
        assert all(row["used_by"] in (None, "") for row in rows)


def test_redeem_credits_balance_once():
    with make_client() as client:
        at = admin_token(client)
        code = client.post("/admin/redeem-codes", headers=auth(at),
                           json={"batch": "t1", "amount_cents": 8000, "count": 1}
                           ).json()["codes"][0]

        token = register(client, PHONE_A)
        r = client.post("/billing/redeem", headers=auth(token), json={"code": code})
        assert r.status_code == 200, r.text
        assert r.json()["balance_cents"] == 8000
        assert r.json()["amount_cents"] == 8000

        # 一码一用：第二次兑换 409
        r2 = client.post("/billing/redeem", headers=auth(token), json={"code": code})
        assert r2.status_code == 409, r2.text

        # 别人也不能用
        tb = register(client, PHONE_B)
        r3 = client.post("/billing/redeem", headers=auth(tb), json={"code": code})
        assert r3.status_code == 409

        # 流水里有 redeem 记录（可复算余额）
        acc = client.get("/billing/account", headers=auth(token)).json()
        assert any(h["kind"] == "redeem" and h["delta_cents"] == 8000
                   for h in acc["history"])


def test_redeem_unknown_code_404():
    with make_client() as client:
        token = register(client, PHONE_A)
        r = client.post("/billing/redeem", headers=auth(token),
                        json={"code": "NOPE-NOT-EXIST"})
        assert r.status_code == 404, r.text


def test_admin_redeem_requires_admin():
    with make_client() as client:
        token = register(client, PHONE_A)
        r = client.post("/admin/redeem-codes", headers=auth(token),
                        json={"batch": "x", "amount_cents": 100, "count": 1})
        assert r.status_code in (401, 403)


# ── 拼团 ───────────────────────────────────────────────────

def test_group_buy_flow_settles_when_full():
    with make_client() as client:
        at = admin_token(client)
        # 给参与者充值：拼团价从余额扣
        ta = register(client, PHONE_A)
        tb = register(client, PHONE_B)
        for tok in (ta, tb):
            client.post("/billing/account/topup", headers=auth(tok),
                        json={"amount_cents": 50000})

        r = client.post("/billing/group-buys", headers=auth(ta),
                        json={"plan_key": "pro", "required": 2,
                              "group_price_cents": 6900, "expires_in_minutes": 60})
        assert r.status_code == 201, r.text
        gb = r.json()
        assert gb["status"] == "open"
        assert gb["joined"] == 1
        assert gb["group_price_cents"] == 6900

        r = client.post(f"/billing/group-buys/{gb['id']}/join", headers=auth(tb))
        assert r.status_code == 200, r.text
        settled = r.json()
        assert settled["status"] == "settled"
        assert settled["joined"] == 2

        # 两人都升级到 pro，且各扣拼团价（不是原价 9900）
        for tok in (ta, tb):
            acc = client.get("/billing/account", headers=auth(tok)).json()
            assert acc["plan_key"] == "pro"
            assert acc["balance_cents"] == 50000 - 6900
            assert any(h["kind"] == "group_buy" for h in acc["history"])


def test_group_buy_join_twice_409():
    with make_client() as client:
        ta = register(client, PHONE_A)
        tb = register(client, PHONE_B)
        for tok in (ta, tb):
            client.post("/billing/account/topup", headers=auth(tok),
                        json={"amount_cents": 50000})
        gb = client.post("/billing/group-buys", headers=auth(ta),
                         json={"plan_key": "pro", "required": 3,
                               "group_price_cents": 5000,
                               "expires_in_minutes": 60}).json()
        client.post(f"/billing/group-buys/{gb['id']}/join", headers=auth(tb))
        r = client.post(f"/billing/group-buys/{gb['id']}/join", headers=auth(tb))
        assert r.status_code == 409, r.text


def test_group_buy_insufficient_balance_402():
    with make_client() as client:
        ta = register(client, PHONE_A)
        tb = register(client, PHONE_B)
        gb = client.post("/billing/group-buys", headers=auth(ta),
                         json={"plan_key": "pro", "required": 2,
                               "group_price_cents": 6900,
                               "expires_in_minutes": 60}).json()
        r = client.post(f"/billing/group-buys/{gb['id']}/join", headers=auth(tb))
        assert r.status_code == 402, r.text


def test_group_buy_expired_410():
    with make_client() as client:
        ta = register(client, PHONE_A)
        tb = register(client, PHONE_B)
        client.post("/billing/account/topup", headers=auth(tb),
                    json={"amount_cents": 50000})
        # expires_in_minutes=0 → 立即过期
        gb = client.post("/billing/group-buys", headers=auth(ta),
                         json={"plan_key": "pro", "required": 2,
                               "group_price_cents": 100,
                               "expires_in_minutes": 0}).json()
        r = client.post(f"/billing/group-buys/{gb['id']}/join", headers=auth(tb))
        assert r.status_code == 410, r.text


def test_group_buy_unknown_plan_404():
    with make_client() as client:
        ta = register(client, PHONE_A)
        r = client.post("/billing/group-buys", headers=auth(ta),
                        json={"plan_key": "不存在", "required": 2,
                              "group_price_cents": 100, "expires_in_minutes": 60})
        assert r.status_code == 404
