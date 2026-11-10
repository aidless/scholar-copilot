"""v1.4：文献三源降级+去重、引用核查多源交叉、job WebSocket 进度、运营日报。"""
import os

import pytest
from fastapi.testclient import TestClient

PW = "Test123456"
ADMIN_PW = os.environ.get("SC_ADMIN_INITIAL_PASSWORD", "")


def make_client():
    from app.main import create_app
    return TestClient(create_app())


def auth(t):
    return {"Authorization": f"Bearer {t}"}


# ---------------------------------------------------------------- 文献三源
def test_litsearch_fallback_and_dedupe(monkeypatch):
    from app import litsearch

    async def boom(q, limit):
        raise RuntimeError("openalex 429")

    async def crossref(q, limit):
        return [
            {"title": "Attention Is All You Need", "doi": "10.1/x", "authors": [], "year": 2017,
             "url": None, "venue": "NeurIPS", "cited_by": 1, "source": "crossref"},
            {"title": "Attention Is All You Need (dup)", "doi": "10.1/X", "authors": [], "year": 2017,
             "url": None, "venue": "NeurIPS", "cited_by": 1, "source": "crossref"},
        ]

    monkeypatch.setattr(litsearch, "_openalex", boom)
    monkeypatch.setattr(litsearch, "_crossref", crossref)
    monkeypatch.setattr(litsearch, "_CACHE", {})

    import asyncio
    out = asyncio.run(litsearch.search_literature("attention", limit=8))
    assert out["source"] == "crossref" and out["cached"] is False
    assert len(out["results"]) == 1  # 同 DOI（大小写不同）去重


def test_litsearch_openalex_polite_params(monkeypatch):
    """配置了 mailto/key 时，OpenAlex 请求应带上礼貌池参数。"""
    from app import litsearch
    from app.config import settings

    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"results": []}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None, headers=None):
            captured.update(params or {})
            return FakeResp()

    monkeypatch.setattr(settings, "openalex_mailto", "lab@example.com")
    monkeypatch.setattr(settings, "openalex_api_key", "KEY123")
    monkeypatch.setattr(litsearch.httpx, "AsyncClient", FakeClient)

    import asyncio
    asyncio.run(litsearch._openalex("q", 5))
    assert captured["mailto"] == "lab@example.com" and captured["api_key"] == "KEY123"


# ---------------------------------------------------------------- 引用核查多源
def test_citecheck_multi_source_cross_verify(monkeypatch):
    from app import citecheck

    async def cr_empty(title): return []
    async def s2_hit(title):
        return [{"title": "Attention Is All You Need", "year": 2017, "venue": "NeurIPS",
                 "doi": "10.5555/xxx", "source": "semantic_scholar"}]

    monkeypatch.setattr(citecheck, "_crossref_title", cr_empty)
    monkeypatch.setattr(citecheck, "_s2_title", s2_hit)
    monkeypatch.setattr(citecheck, "_CACHE", {})

    import asyncio
    out = asyncio.run(citecheck.verify_citation("Attention is all you need", year=2017))
    assert out["state"] == "verified"
    assert out["evidence"]["source"] == "semantic_scholar"


def test_citecheck_all_sources_down_raises(monkeypatch):
    from app import citecheck

    async def boom(title): raise RuntimeError("503")

    monkeypatch.setattr(citecheck, "_crossref_title", boom)
    monkeypatch.setattr(citecheck, "_s2_title", boom)
    monkeypatch.setattr(citecheck, "_CACHE", {})

    import asyncio
    with pytest.raises(RuntimeError):
        asyncio.run(citecheck.verify_citation("some title"))


# ---------------------------------------------------------------- WebSocket 进度
def test_job_websocket_progress_and_ownership():
    with make_client() as client:
        tok = client.post("/auth/register", json={
            "phone": "13800000101", "password": PW, "check_code": "000000"}).json()["access_token"]
        o = client.post("/writing/orders", headers=auth(tok), json={
            "title": "WS 进度", "education": "本科", "word_count": 6000}).json()
        job_id = client.post(f"/writing/orders/{o['id']}/outline?wait=true",
                             headers=auth(tok), json={"feedback": None}).json()["job"]["job_id"]

        with client.websocket_connect(f"/jobs/{job_id}/ws?token={tok}") as ws:
            snap = ws.receive_json()
            assert snap["job_id"] == job_id and snap["status"] == "done"

        # 别人的 token → 1008 关闭（不泄露任务存在性）
        other = client.post("/auth/register", json={
            "phone": "13800000102", "password": PW, "check_code": "000000"}).json()["access_token"]
        with client.websocket_connect(f"/jobs/{job_id}/ws?token={other}") as ws:
            with pytest.raises(Exception):
                ws.receive_json()


# ---------------------------------------------------------------- 运营日报
def test_admin_report_summary():
    with make_client() as client:
        adm = client.post("/admin/login", json={"username": "admin", "password": ADMIN_PW}).json()["access_token"]
        r = client.get("/admin/reports/summary?days=7", headers=auth(adm))
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        for k in ("window_days", "revenue_cents", "orders_new", "new_users",
                  "jobs_by_status", "tokens_in", "tokens_out"):
            assert k in body
        assert client.get("/admin/reports/summary?days=0", headers=auth(adm)).status_code == 422


# ---------------------------------------------------------------- PubMed 第四源（v1.6）
def test_pubmed_norm_extracts_doi_and_year():
    """esummary 的 doi 在 articleids 里、年份在 pubdate 前四位——两处都容易取错。"""
    from app.litsearch import _norm_pubmed

    item = {
        "uid": "12345",
        "title": "A Study of Things.",
        "pubdate": "2021 Mar 15",
        "fulljournalname": "Journal of Things",
        "authors": [{"name": "Zhang San"}, {"name": "Li Si"}],
        "articleids": [
            {"idtype": "pubmed", "value": "12345"},
            {"idtype": "doi", "value": "10.1000/xyz"},
        ],
    }
    out = _norm_pubmed(item)
    assert out["title"] == "A Study of Things"          # 去掉句末点
    assert out["year"] == 2021
    assert out["doi"] == "10.1000/xyz"                  # 挑 doi 而不是 pubmed id
    assert out["url"] == "https://doi.org/10.1000/xyz"
    assert out["venue"] == "Journal of Things"
    assert out["source"] == "pubmed"
    assert out["authors"] == ["Zhang San", "Li Si"]


def test_pubmed_norm_without_doi_falls_back_to_pubmed_url():
    from app.litsearch import _norm_pubmed

    out = _norm_pubmed({"uid": "999", "title": "No DOI Paper", "pubdate": "2019",
                        "authors": [], "articleids": []})
    assert out["doi"] == ""
    assert out["url"] == "https://pubmed.ncbi.nlm.nih.gov/999/"
    assert out["year"] == 2019


def test_pubmed_norm_skips_empty_title():
    from app.litsearch import _norm_pubmed

    assert _norm_pubmed({"uid": "1", "title": "  "}) is None
    assert _norm_pubmed({"uid": "2"}) is None


def test_pubmed_passes_api_key_and_email(monkeypatch):
    """配了 key/email 就该带上（NCBI 用它提额，匿名 3 req/s 容易被限）。"""
    from app import litsearch
    from app.config import settings

    seen = []

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"esearchresult": {"idlist": []}}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None, headers=None):
            seen.append((url, params or {}))
            return FakeResp()

    monkeypatch.setattr(settings, "pubmed_api_key", "PKEY")
    monkeypatch.setattr(settings, "pubmed_email", "lab@example.com")
    monkeypatch.setattr(litsearch.httpx, "AsyncClient", FakeClient)

    import asyncio
    asyncio.run(litsearch._pubmed("q", 5))
    assert len(seen) == 1  # esearch 无结果就不再打 esummary
    url, params = seen[0]
    assert "esearch" in url
    assert params["api_key"] == "PKEY" and params["email"] == "lab@example.com"
    assert params["db"] == "pubmed" and params["retmode"] == "json"


def test_pubmed_disabled_is_not_in_chain(monkeypatch):
    """pubmed_enabled=false 时不该被调用（有些部署只想要 DOI 库，不想拉医学库）。"""
    from app import litsearch
    from app.config import settings

    called = {"pubmed": False}

    async def boom(q, limit): raise RuntimeError("down")
    async def empty(q, limit): return []
    async def pubmed(q, limit):
        called["pubmed"] = True
        return []

    monkeypatch.setattr(litsearch, "_openalex", boom)
    monkeypatch.setattr(litsearch, "_crossref", boom)
    monkeypatch.setattr(litsearch, "_semantic", boom)
    monkeypatch.setattr(litsearch, "_pubmed", pubmed)
    monkeypatch.setattr(settings, "pubmed_enabled", False)
    monkeypatch.setattr(litsearch, "_CACHE", {})

    import asyncio
    with pytest.raises(RuntimeError):
        asyncio.run(litsearch.search_literature("q", limit=3))
    assert called["pubmed"] is False
