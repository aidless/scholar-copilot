"""v0.3：文献检索（monkeypatch 免网络）/ 挂单 / 降重改写（fake provider）/ 检测启发式。"""
import time

from fastapi.testclient import TestClient

PHONE_A = "13800000011"
PHONE_B = "13800000012"
PW = "Test123456"

FAKE_SEARCH = {
    "results": [
        {"title": "Attention Is All You Need", "authors": ["Vaswani"],
         "year": 2017, "doi": "10.5555/3295222", "url": "https://doi.org/10.5555/3295222",
         "venue": "NeurIPS", "cited_by": 90000, "source": "crossref"},
        {"title": "GPT-4 Technical Report", "authors": ["OpenAI"],
         "year": 2023, "doi": None, "url": "https://arxiv.org/abs/2303.08774",
         "venue": None, "cited_by": 1200, "source": "crossref"},
    ],
    "source": "crossref", "cached": False,
}


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


def setup_order(client: TestClient, token: str) -> str:
    """注册→下单→大纲→支付→生成 ch1，返回 order_id。"""
    order = client.post("/writing/orders",
                        json={"title": "基于大语言模型的学术写作助手研究", "education": "硕士",
                              "word_count": 10000},
                        headers=auth(token)).json()
    client.post(f"/writing/orders/{order['id']}/outline?wait=true", json={}, headers=auth(token))
    pay_order(client, token, order["id"])
    r = client.post(f"/writing/orders/{order['id']}/chapters/ch1?wait=true",
                    json=None, headers=auth(token))
    assert r.status_code == 200, r.text
    return order["id"]


# ── 文献检索 ─────────────────────────────────────────────────

def test_search_ok_and_502(monkeypatch):
    with make_client() as client:
        import app.routers.references as refs

        async def fake_ok(q, limit=8):
            return dict(FAKE_SEARCH)

        async def fake_down(q, limit=8):
            raise RuntimeError("所有文献源不可用：openalex: 429; crossref: timeout")

        monkeypatch.setattr(refs, "search_literature", fake_ok)
        r = client.get("/references/search", params={"q": "transformer"})
        assert r.status_code == 200
        body = r.json()
        assert body["source"] == "crossref"
        assert len(body["results"]) == 2
        assert body["results"][0]["doi"] == "10.5555/3295222"

        monkeypatch.setattr(refs, "search_literature", fake_down)
        r = client.get("/references/search", params={"q": "transformer"})
        assert r.status_code == 502
        assert "不可用" in r.json()["detail"]


def test_attach_and_list_refs():
    with make_client() as client:
        token = register(client, PHONE_A)
        order_id = setup_order(client, token)

        r = client.post(f"/references/orders/{order_id}", headers=auth(token),
                        json={"items": [
                            {"title": "Attention Is All You Need", "authors": ["Vaswani"],
                             "year": 2017, "doi": "10.5555/3295222"},
                            {"title": "某网页资料", "kind": "web", "url": "https://example.com/a"},
                        ]})
        assert r.status_code == 200
        assert r.json()["attached"] == 2

        r = client.get(f"/references/orders/{order_id}", headers=auth(token))
        rows = r.json()
        assert len(rows) == 2
        assert rows[0]["verify_state"] == "unverified"
        assert rows[0]["authors"] == "Vaswani"
        assert rows[1]["kind"] == "web"

        # IDOR：B 查 A 的文献单 → 404
        tb = register(client, PHONE_B)
        assert client.get(f"/references/orders/{order_id}",
                          headers=auth(tb)).status_code == 404


# ── 降重/改写 ────────────────────────────────────────────────

def test_rewrite_tool_endpoint():
    """独立工具改写（不落库）走 fake provider。"""
    with make_client() as client:
        r = client.post("/tools/rewrite",
                        json={"text": "综上所述，本文提出了一种具有重要意义的方法。",
                              "instruction": "去掉套话，改具体"})
        assert r.status_code == 200
        body = r.json()
        assert body["model"] == "fake-model"
        assert "改写" in body["text"] or len(body["text"]) > 0


def test_chapter_rewrite_keeps_a_and_upgrades_c():
    """A/B 章 AI 改写后仍 A；C（人工）被 AI 改写 → 如实升 B。"""
    with make_client() as client:
        token = register(client, PHONE_A)
        order_id = setup_order(client, token)

        # 生成后 ai_level=A → AI 改写后仍 A
        r = client.post(f"/writing/orders/{order_id}/chapters/ch1/rewrite?wait=true",
                        json={"instruction": "压缩冗余"}, headers=auth(token))
        assert r.status_code == 200, r.text
        assert r.json()["chapter"]["ai_level"] == "A"
        assert r.json()["job"]["status"] == "done"
        assert r.json()["chapter"]["word_count"] > 0

        # 用户手动改稿标记为 C（人工撰写）
        r = client.put(f"/writing/orders/{order_id}/chapters/ch1",
                       json={"content_md": "这一段由用户亲手撰写。", "ai_level": "C"},
                       headers=auth(token))
        assert r.status_code == 200
        assert r.json()["ai_level"] == "C"

        # AI 改写人工正文 → 如实升 B
        r = client.post(f"/writing/orders/{order_id}/chapters/ch1/rewrite?wait=true",
                        json=None, headers=auth(token))
        assert r.status_code == 200
        assert r.json()["chapter"]["ai_level"] == "B"


def test_chapter_rewrite_background_and_ownership():
    with make_client() as client:
        ta = register(client, PHONE_A)
        tb = register(client, PHONE_B)
        order_id = setup_order(client, ta)

        r = client.post(f"/writing/orders/{order_id}/chapters/ch1/rewrite?wait=false",
                        json=None, headers=auth(ta))
        assert r.status_code == 200
        job_id = r.json()["job_id"]

        # B 的同路径操作 → 404（章节不归 B）
        r = client.post(f"/writing/orders/{order_id}/chapters/ch1/rewrite?wait=true",
                        json=None, headers=auth(tb))
        assert r.status_code == 404

        deadline = time.time() + 10
        status = None
        while time.time() < deadline:
            r = client.get(f"/jobs/{job_id}", headers=auth(ta))
            status = r.json()["status"]
            if status == "done":
                break
            time.sleep(0.2)
        assert status == "done"


# ── 检测（启发式） ───────────────────────────────────────────

def test_detect_heuristic_signals():
    text = ("综上所述，随着经济的快速发展，该方法具有重要意义。" * 3
            + "实证结果如表 1 所示 [1]，进一步验证了模型的有效性 [2]。")
    with make_client() as client:
        r = client.post("/tools/detect", json={"text": text})
        assert r.status_code == 200
        body = r.json()
        assert body["metrics"]["cjk_chars"] > 50
        assert body["metrics"]["citation_markers"] == 2
        assert body["cliche"]["hits"], "套话清单应命中"
        assert "综上所述" in body["cliche"]["hits"]
        assert body["advice"]
        assert "非查重率" in body["disclaimer"]


def test_detect_rejects_short_text():
    with make_client() as client:
        r = client.post("/tools/detect", json={"text": "太短"})
        assert r.status_code == 422
