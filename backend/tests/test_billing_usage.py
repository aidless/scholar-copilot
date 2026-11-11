"""v1.12 #18：token 级用量计量 + 套餐/余额账户。

原产品计费只到「订单付了多少钱」，看不到钱花在哪个任务/哪个模型上，也没有套餐
与余额。这里补两面：
- 用量侧：每次 LLM 调用落一条 usage_records（tokens_in/out + 按价表折算成本）；
- 账户侧：`accounts` 表记套餐 + 余额，订阅扣余额并落流水；用量超套餐软提示。
"""
import pytest
from fastapi.testclient import TestClient

PHONE_A = "13800000041"
PHONE_B = "13800000042"
PW = "Test123456"


def make_client():
    from app.main import create_app
    return TestClient(create_app())


def register(client, phone):
    r = client.post("/auth/register",
                    json={"phone": phone, "password": PW, "check_code": "000000"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── 纯函数层 ────────────────────────────────────────────────

def test_cost_cents_uses_price_table():
    from app.billing import cost_cents

    # deepseek-chat：输入 0.001 元/千、输出 0.002 元/千
    # 10 万 in + 10 万 out = 0.1 + 0.2 = 0.3 元 = 30 分
    assert cost_cents("deepseek-chat", 100000, 100000) == 30
    # 线性：10 倍 token → 10 倍成本
    assert cost_cents("deepseek-chat", 10000, 10000) == 3
    # 贵的模型更贵
    assert cost_cents("gpt-4o", 100000, 100000) > cost_cents("deepseek-chat", 100000, 100000)


def test_cost_cents_zero_for_fake_model():
    from app.billing import cost_cents

    assert cost_cents("fake-model", 10 ** 6, 10 ** 6) == 0


def test_plans_table_is_visible_and_ordered():
    from app.billing import PLANS

    assert "free" in PLANS and "pro" in PLANS
    for key, plan in PLANS.items():
        assert plan["price_cents"] >= 0, key
        assert plan["token_quota"] > 0, key


# ── 用量记账 ────────────────────────────────────────────────

def test_generation_records_usage_rows():
    with make_client() as client:
        token = register(client, PHONE_A)
        order = client.post("/writing/orders",
                            json={"title": "用量计量论文", "education": "本科",
                                  "word_count": 5000},
                            headers=auth(token)).json()
        client.post(f"/writing/orders/{order['id']}/outline?wait=true", json={},
                    headers=auth(token))

        r = client.get("/billing/usage", headers=auth(token))
        assert r.status_code == 200, r.text
        body = r.json()
        # 大纲生成 = 至少一条 usage 记录，且带 token 与成本
        assert body["total_calls"] >= 1
        assert body["total_tokens_in"] > 0
        assert body["total_tokens_out"] > 0
        kinds = {row["kind"] for row in body["by_kind"]}
        assert "outline" in kinds
        row = next(x for x in body["by_kind"] if x["kind"] == "outline")
        assert row["calls"] >= 1
        assert row["tokens_out"] > 0
        assert "cost_cents" in row


def test_usage_is_scoped_to_owner():
    with make_client() as client:
        ta = register(client, PHONE_A)
        order = client.post("/writing/orders",
                            json={"title": "A 的论文", "education": "本科", "word_count": 5000},
                            headers=auth(ta)).json()
        client.post(f"/writing/orders/{order['id']}/outline?wait=true", json={},
                    headers=auth(ta))

        tb = register(client, PHONE_B)
        r = client.get("/billing/usage", headers=auth(tb)).json()
        assert r["total_calls"] == 0  # 别人的用量不可见
        assert r["total_tokens_in"] == 0


# ── 套餐与余额 ─────────────────────────────────────────────

def test_plans_endpoint():
    with make_client() as client:
        token = register(client, PHONE_A)
        r = client.get("/billing/plans", headers=auth(token))
        assert r.status_code == 200, r.text
        plans = r.json()["plans"]
        keys = [p["key"] for p in plans]
        assert "free" in keys
        assert plans == sorted(plans, key=lambda p: p["price_cents"])


def test_account_defaults_to_free_plan():
    with make_client() as client:
        token = register(client, PHONE_A)
        r = client.get("/billing/account", headers=auth(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["plan_key"] == "free"
        assert body["balance_cents"] == 0
        assert body["token_quota"] > 0
        assert body["tokens_used"] == 0


def test_subscribe_deducts_balance_and_switches_plan():
    with make_client() as client:
        token = register(client, PHONE_A)
        # 直接充值（演示模式允许自充，便于本地跑通；生产应接支付回调）
        r = client.post("/billing/account/topup", headers=auth(token),
                        json={"amount_cents": 100000})
        assert r.status_code == 200, r.text
        assert r.json()["balance_cents"] == 100000

        r = client.post("/billing/plans/pro/subscribe", headers=auth(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["plan_key"] == "pro"
        assert body["balance_cents"] == 100000 - body["charged_cents"]
        assert body["charged_cents"] > 0

        acc = client.get("/billing/account", headers=auth(token)).json()
        assert acc["plan_key"] == "pro"
        # 流水可查：账单按时间倒序，最新一条应是订阅扣款
        assert acc["history"][0]["kind"] == "subscribe"
        assert acc["history"][0]["delta_cents"] < 0


def test_subscribe_insufficient_balance_402():
    with make_client() as client:
        token = register(client, PHONE_A)
        r = client.post("/billing/plans/pro/subscribe", headers=auth(token))
        assert r.status_code == 402, r.text


def test_subscribe_unknown_plan_404():
    with make_client() as client:
        token = register(client, PHONE_A)
        client.post("/billing/account/topup", headers=auth(token),
                    json={"amount_cents": 100000})
        r = client.post("/billing/plans/不存在的套餐/subscribe", headers=auth(token))
        assert r.status_code == 404


def test_account_requires_auth():
    with make_client() as client:
        assert client.get("/billing/account").status_code in (401, 403)
