"""v0.4：引用真实性核查（monkeypatch 免网络）+ 格式排版 profile。"""
import pytest
from fastapi.testclient import TestClient

PHONE_A = "13800000041"
PHONE_B = "13800000042"
PW = "Test123456"

GOOD_EVIDENCE = {"method": "doi-lookup", "source": "crossref",
                 "matched_title": "Attention Is All You Need", "matched_year": 2017}


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
    r = client.post(f"/payments/{r.json()['serial_no']}/confirm", headers=auth(token))
    assert r.status_code == 200, r.text


def full_order(client: TestClient, token: str) -> str:
    """下单→大纲→支付→全部章节生成（fake provider 秒回），返回 order_id。"""
    order = client.post("/writing/orders",
                        json={"title": "基于大语言模型的学术写作助手研究", "education": "硕士",
                              "word_count": 10000},
                        headers=auth(token)).json()
    client.post(f"/writing/orders/{order['id']}/outline?wait=true", json={}, headers=auth(token))
    pay_order(client, token, order["id"])
    for node in ["ch1", "ch2", "ch3", "ch4", "ch5"]:
        r = client.post(f"/writing/orders/{order['id']}/chapters/{node}?wait=true",
                        json=None, headers=auth(token))
        assert r.status_code == 200, r.text
    return order["id"]


# ── 引用核查 ─────────────────────────────────────────────────

def test_verify_items_endpoint(monkeypatch):
    with make_client() as client:
        import app.routers.references as refs

        async def fake_check(title, doi=None, year=None):
            if doi == "10.5555/3295222":
                return {"state": "verified", "similarity": 1.0,
                        "evidence": {**GOOD_EVIDENCE, "matched_doi": doi}}
            return {"state": "fake", "similarity": 0.12,
                    "evidence": {"method": "title-match", "matched_title": None}}

        monkeypatch.setattr(refs, "check_citation", fake_check)
        r = client.post("/references/verify", headers=None, json={"items": [
            {"title": "Attention Is All You Need", "doi": "10.5555/3295222", "year": 2017},
            {"title": "完全编造的不存在的论文标题 2026", "year": 2026},
        ]})
        assert r.status_code == 200
        results = r.json()["results"]
        assert results[0]["state"] == "verified"
        assert results[0]["evidence"]["matched_doi"] == "10.5555/3295222"
        assert results[1]["state"] == "fake"
        assert results[1]["similarity"] == 0.12

        async def down(title, doi=None, year=None):
            raise RuntimeError("核查源不可用：crossref timeout")

        monkeypatch.setattr(refs, "check_citation", down)
        r = client.post("/references/verify", json={"items": [{"title": "任意标题"}]})
        assert r.status_code == 502


def test_order_verify_updates_rows_and_report(monkeypatch):
    with make_client() as client:
        import app.routers.references as refs

        token = register(client, PHONE_A)
        order_id = full_order(client, token)
        r = client.post(f"/references/orders/{order_id}", headers=auth(token),
                        json={"items": [
                            {"title": "Attention Is All You Need", "doi": "10.5555/3295222",
                             "year": 2017},
                            {"title": "虚构论文标题", "year": 2026},
                        ]})
        assert r.status_code == 200

        calls = []

        async def fake_check(title, doi=None, year=None):
            calls.append(title)
            state = "verified" if doi else "fake"
            return {"state": state, "similarity": 1.0 if doi else 0.1,
                    "evidence": {"method": "doi-lookup" if doi else "title-match",
                                 "matched_title": title if doi else None}}

        monkeypatch.setattr(refs, "check_citation", fake_check)
        r = client.post(f"/references/orders/{order_id}/verify", headers=auth(token))
        assert r.status_code == 200
        body = r.json()
        assert body["checked"] == 2
        assert body["summary"] == {"verified": 1, "suspicious": 0, "fake": 1, "unverified": 0}
        assert body["all_real"] is False
        assert len(calls) == 2

        # 行已更新：GET 列表带 state + evidence
        rows = client.get(f"/references/orders/{order_id}", headers=auth(token)).json()
        assert rows[0]["verify_state"] == "verified"
        assert rows[1]["verify_state"] == "fake"
        assert rows[1]["verify_evidence"]["method"] == "title-match"

        # IDOR
        tb = register(client, PHONE_B)
        assert client.post(f"/references/orders/{order_id}/verify",
                           headers=auth(tb)).status_code == 404

        # 空文献 409
        order2 = client.post("/writing/orders",
                             json={"title": "空订单", "education": "本科", "word_count": 5000},
                             headers=auth(token)).json()
        r = client.post(f"/references/orders/{order2['id']}/verify", headers=auth(token))
        assert r.status_code == 409


# ── 格式排版 ─────────────────────────────────────────────────

def test_format_profiles_listing():
    with make_client() as client:
        r = client.get("/formatting/profiles")
        assert r.status_code == 200
        profiles = {p["key"] for p in r.json()}
        assert profiles == {"本科-通用", "硕士-通用", "博士-通用", "英文-通用"}
        sample = r.json()[0]
        assert sample["body"]["size_pt"] == 12
        assert sample["headings"]["heading1"]["size_pt"] >= 14


def test_export_with_format_profile():
    with make_client() as client:
        token = register(client, PHONE_A)
        order_id = full_order(client, token)

        r_default = client.post(f"/writing/orders/{order_id}/export", headers=auth(token))
        assert r_default.status_code == 200
        assert r_default.content[:2] == b"PK"

        # profile 导出：PK 魔数 + 尺寸合理
        r_fmt = client.post(f"/writing/orders/{order_id}/export?profile=硕士-通用",
                            headers=auth(token))
        assert r_fmt.status_code == 200, r_fmt.text
        assert r_fmt.content[:2] == b"PK"
        assert len(r_fmt.content) > 10000

        # 未知 profile → 422
        r = client.post(f"/writing/orders/{order_id}/export?profile=不存在大学",
                        headers=auth(token))
        assert r.status_code == 422
        assert "formatting/profiles" in r.json()["detail"]
