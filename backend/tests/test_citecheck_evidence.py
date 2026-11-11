"""v1.12 #20：引用核查证据链可视化——Top-N 候选 + 条形图。

原产品只给一个 0.905 的分数，用户无法判断「像哪篇」。这里让核查结果暴露
候选列表（标题/年份/期刊/DOI/来源/相似度，按相似度降序），并能直接渲染成
条形图 PNG，让「引用核查」变成可复核的证据链而不是黑箱分数。
"""
import pytest
from fastapi.testclient import TestClient

PHONE_A = "13800000041"
PHONE_B = "13800000042"
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


def _crossref_stub(monkeypatch):
    """把三个外部源都换成本地桩，保证测试零网络且可断言候选排序。"""
    import app.citecheck as cc

    async def crossref_title(title):
        return [
            {"title": "Attention Is All You Need", "year": 2017,
             "venue": "NeurIPS", "doi": "10.5555/3295222"},
            {"title": "Attention Is All You Need for Chinese", "year": 2019,
             "venue": "预印本", "doi": "10.5555/3295223"},
            {"title": "A Totally Different Paper", "year": 2020,
             "venue": "Other", "doi": "10.5555/3295224"},
        ]

    async def s2_title(title):
        return []

    async def pubmed_title(title):
        return []

    monkeypatch.setattr(cc, "_crossref_title", crossref_title)
    monkeypatch.setattr(cc, "_s2_title", s2_title)
    monkeypatch.setattr(cc, "_pubmed_title", pubmed_title)
    monkeypatch.setattr(cc.settings, "pubmed_enabled", False)


# ── 纯函数层：verify_citation 暴露 Top-N 候选 ────────────────────

@pytest.mark.anyio
async def test_verify_returns_sorted_top_candidates(monkeypatch):
    _crossref_stub(monkeypatch)
    import app.citecheck as cc

    result = await cc.verify_citation("Attention Is All You Need")
    assert result["state"] == "verified"
    cands = result["candidates"]
    assert len(cands) == 3
    # 按相似度降序
    sims = [c["similarity"] for c in cands]
    assert sims == sorted(sims, reverse=True)
    assert cands[0]["title"] == "Attention Is All You Need"
    assert cands[0]["doi"] == "10.5555/3295222"
    assert cands[0]["source"] == "crossref"
    # 候选里必须带年份与期刊，才能让人自己判断是不是同一篇
    assert cands[0]["year"] == 2017
    assert cands[0]["venue"] == "NeurIPS"


@pytest.mark.anyio
async def test_verify_doi_lookup_has_single_candidate(monkeypatch):
    import app.citecheck as cc

    async def crossref_doi(doi):
        return {"title": "Attention Is All You Need", "year": 2017,
                "venue": "NeurIPS", "doi": doi}

    monkeypatch.setattr(cc, "_crossref_doi", crossref_doi)
    result = await cc.verify_citation("Attention Is All You Need", doi="10.5555/3295222")
    assert result["state"] == "verified"
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["similarity"] == 1.0


@pytest.mark.anyio
async def test_verify_candidates_capped_by_top_k(monkeypatch):
    _crossref_stub(monkeypatch)
    import app.citecheck as cc

    result = await cc.verify_citation("Attention Is All You Need", top_k=2)
    assert len(result["candidates"]) == 2


# ── API 层：证据链端点 + 条形图 ────────────────────────────────

def test_verify_evidence_endpoint_returns_candidates_and_chart(monkeypatch):
    with make_client() as client:
        import app.routers.references as refs

        async def fake_check(title, doi=None, year=None, top_k=5):
            cands = [
                {"title": "Attention Is All You Need", "year": 2017,
                 "venue": "NeurIPS", "doi": "10.5555/3295222", "source": "crossref",
                 "similarity": 0.97},
                {"title": "Attention Is All You Need for Chinese", "year": 2019,
                 "venue": "预印本", "doi": "10.5555/3295223", "source": "crossref",
                 "similarity": 0.83},
                {"title": "A Totally Different Paper", "year": 2020,
                 "venue": "Other", "doi": "10.5555/3295224", "source": "crossref",
                 "similarity": 0.21},
            ]
            return {"state": "verified", "similarity": 0.97,
                    "candidates": cands[:top_k],
                    "evidence": {"method": "title-match", "source": "crossref",
                                 "matched_title": cands[0]["title"], "matched_year": 2017}}

        monkeypatch.setattr(refs, "check_citation", fake_check)
        r = client.post("/references/verify/evidence", json={
            "items": [{"title": "Attention Is All You Need", "year": 2017}]})
        assert r.status_code == 200, r.text
        body = r.json()
        item = body["results"][0]
        assert len(item["candidates"]) == 3
        # 条形图规格：labels 与 values 一一对应，可直接喂给 /tools/chart
        chart = item["chart"]
        assert chart["type"] == "bar"
        assert len(chart["labels"]) == 3
        assert len(chart["series"][0]["values"]) == 3
        assert chart["series"][0]["values"] == [0.97, 0.83, 0.21]
        assert chart["ylabel"] == "相似度"


def test_verify_evidence_chart_returns_png(monkeypatch):
    with make_client() as client:
        import app.routers.references as refs

        async def fake_check(title, doi=None, year=None, top_k=5):
            return {"state": "suspicious", "similarity": 0.66, "candidates": [
                {"title": "候选一", "year": 2020, "venue": "V", "doi": "10.1/a",
                 "source": "crossref", "similarity": 0.66},
                {"title": "候选二", "year": 2021, "venue": "V", "doi": "10.1/b",
                 "source": "crossref", "similarity": 0.31},
            ], "evidence": {"method": "title-match", "matched_title": "候选一"}}

        monkeypatch.setattr(refs, "check_citation", fake_check)
        r = client.post("/references/verify/evidence/chart", json={
            "title": "某条可疑引用"})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("image/png")
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_order_evidence_lists_stored_candidates(monkeypatch):
    with make_client() as client:
        import app.routers.references as refs

        token = register(client, PHONE_A)
        order = client.post("/writing/orders",
                            json={"title": "证据链订单", "education": "本科", "word_count": 5000},
                            headers=auth(token)).json()
        client.post(f"/references/orders/{order['id']}", headers=auth(token), json={"items": [
            {"title": "Attention Is All You Need", "doi": "10.5555/3295222", "year": 2017}]})

        async def fake_check(title, doi=None, year=None, top_k=5):
            return {"state": "verified", "similarity": 1.0, "candidates": [
                {"title": "Attention Is All You Need", "year": 2017, "venue": "NeurIPS",
                 "doi": "10.5555/3295222", "source": "crossref", "similarity": 1.0},
            ], "evidence": {"method": "doi-lookup", "source": "crossref",
                            "matched_title": title, "matched_year": 2017}}

        monkeypatch.setattr(refs, "check_citation", fake_check)
        r = client.post(f"/references/orders/{order['id']}/verify", headers=auth(token))
        assert r.status_code == 200, r.text

        r = client.get(f"/references/orders/{order['id']}/evidence", headers=auth(token))
        assert r.status_code == 200, r.text
        rows = r.json()["results"]
        assert len(rows) == 1
        assert rows[0]["candidates"][0]["similarity"] == 1.0
        assert rows[0]["chart"]["type"] == "bar"

        # IDOR
        tb = register(client, PHONE_B)
        assert client.get(f"/references/orders/{order['id']}/evidence",
                          headers=auth(tb)).status_code == 404
