"""v1.12 #21：离线模式 + 本地文献库（BibTeX / CNKI 文本导入）。

为什么需要：内网/断网环境下，/references/search 走外网三源必然超时，
论文写不下去。离线模式让整套流程（大纲→章节→核查）都不依赖外网：
- 文献检索改为查本地库（用户自己导入的 BibTeX / CNKI 导出文本）；
- 引用核查只用本地库做标题匹配，明确标注「本地库未命中 ≠ 文献不存在」。
"""
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

PHONE = "13910000021"
PW = "Test123456"

BIBTEX = """
@article{vaswani2017attention,
  title = {Attention is All You Need},
  author = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki},
  journal = {NeurIPS},
  year = {2017},
  doi = {10.48550/arXiv.1706.03762}
}

@book{goodfellow2016deep,
  title = {Deep Learning},
  author = {Goodfellow, Ian and Bengio, Yoshua and Courville, Aaron},
  publisher = {MIT Press},
  year = {2016}
}
"""

CNKI_TEXT = """题名：基于大模型的学术写作辅助系统设计
作者：张三;李四
来源：计算机应用研究
年：2024
摘要：本文设计了一套面向学术写作的辅助系统。

题名：中文文献去重方法综述
作者：王五
来源：情报学报
年：2022
"""


@contextmanager
def make_client(offline=False):
    """开关必须撑到 with 结束：断点请求时读的是 settings 现值。"""
    from app.config import settings
    from app.main import create_app
    old = settings.offline_mode
    settings.offline_mode = offline
    try:
        with TestClient(create_app()) as client:
            yield client
    finally:
        settings.offline_mode = old


def register(client):
    r = client.post("/auth/register",
                    json={"phone": PHONE, "password": PW, "check_code": "000000"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── 解析器（纯函数） ────────────────────────────────────────

def test_parse_bibtex_extracts_fields():
    from app.offline import parse_bibtex

    items = parse_bibtex(BIBTEX)
    assert len(items) == 2
    first = next(i for i in items if "Attention" in i["title"])
    assert first["year"] == 2017
    assert first["venue"] == "NeurIPS"
    assert first["doi"] == "10.48550/arXiv.1706.03762"
    assert first["authors"][0] == "Vaswani, Ashish"
    assert first["kind"] == "journal"

    book = next(i for i in items if "Deep Learning" in i["title"])
    assert book["kind"] == "book"
    assert book["venue"] == "MIT Press"


def test_parse_cnki_extracts_records():
    from app.offline import parse_cnki

    items = parse_cnki(CNKI_TEXT)
    assert len(items) == 2
    assert items[0]["title"].startswith("基于大模型的学术写作")
    assert items[0]["authors"] == ["张三", "李四"]
    assert items[0]["year"] == 2024
    assert items[0]["venue"] == "计算机应用研究"
    assert items[0]["kind"] == "journal"


def test_parse_empty_input_returns_empty_list():
    from app.offline import parse_bibtex, parse_cnki

    assert parse_bibtex("") == []
    assert parse_cnki("   \n\n") == []


def test_local_search_matches_title_and_author():
    from app.offline import parse_bibtex, parse_cnki, search_local

    items = parse_bibtex(BIBTEX) + parse_cnki(CNKI_TEXT)
    assert len(search_local("attention", items, limit=5)) == 1
    assert len(search_local("张三", items, limit=5)) == 1
    assert search_local("完全不相关的查询词", items, limit=5) == []


# ── HTTP 端点 ──────────────────────────────────────────────

def test_import_bibtex_then_list_and_search():
    with make_client() as client:
        token = register(client)
        r = client.post("/references/library/import", headers=auth(token),
                        json={"format": "bibtex", "content": BIBTEX})
        assert r.status_code == 201, r.text
        assert r.json()["imported"] == 2
        assert r.json()["skipped"] == 0

        # 重复导入不重复入库（按标题+年份去重）
        r2 = client.post("/references/library/import", headers=auth(token),
                         json={"format": "bibtex", "content": BIBTEX})
        assert r2.json()["imported"] == 0
        assert r2.json()["skipped"] == 2

        r = client.get("/references/library", headers=auth(token))
        assert r.status_code == 200
        assert r.json()["total"] == 2

        r = client.post("/references/library/search", headers=auth(token),
                        json={"q": "Attention", "limit": 5})
        assert r.status_code == 200, r.text
        hits = r.json()["items"]
        assert len(hits) == 1
        assert hits[0]["year"] == 2017


def test_import_cnki_text():
    with make_client() as client:
        token = register(client)
        r = client.post("/references/library/import", headers=auth(token),
                        json={"format": "cnki", "content": CNKI_TEXT})
        assert r.status_code == 201, r.text
        assert r.json()["imported"] == 2
        r = client.post("/references/library/search", headers=auth(token),
                        json={"q": "去重", "limit": 5})
        assert len(r.json()["items"]) == 1


def test_import_bad_format_422_and_empty_422():
    with make_client() as client:
        token = register(client)
        r = client.post("/references/library/import", headers=auth(token),
                        json={"format": "不支持的格式", "content": BIBTEX})
        assert r.status_code == 422, r.text
        r = client.post("/references/library/import", headers=auth(token),
                        json={"format": "bibtex", "content": ""})
        assert r.status_code == 422, r.text


def test_library_is_scoped_to_owner():
    with make_client() as client:
        t1 = register(client)
        client.post("/references/library/import", headers=auth(t1),
                    json={"format": "bibtex", "content": BIBTEX})
        # 换一个用户（同库不同手机号）
        r = client.post("/auth/register",
                        json={"phone": "13910000022", "password": PW,
                              "check_code": "000000"})
        t2 = r.json()["access_token"]
        assert client.get("/references/library", headers=auth(t2)).json()["total"] == 0


def test_offline_mode_serves_search_from_local_library():
    with make_client(offline=True) as client:
        token = register(client)
        client.post("/references/library/import", headers=auth(token),
                    json={"format": "bibtex", "content": BIBTEX})
        r = client.get("/references/search?q=Attention&limit=5", headers=auth(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "local"
        assert len(body["items"]) >= 1
        assert body["items"][0]["title"].startswith("Attention")


def test_online_mode_uses_remote_sources():
    with make_client(offline=False) as client:
        token = register(client)
        # 在线模式下 source 不应是 local（fake 环境下 litsearch 会用 httpx 打外网，
        # 失败即 502；这里只断言「不走本地库」这一契约）
        r = client.get("/references/search?q=Attention&limit=3", headers=auth(token))
        if r.status_code == 200:
            assert r.json().get("source") != "local"
        else:
            assert r.status_code == 502


def test_offline_verify_uses_local_library():
    with make_client(offline=True) as client:
        token = register(client)
        client.post("/references/library/import", headers=auth(token),
                    json={"format": "bibtex", "content": BIBTEX})
        r = client.post("/references/verify", headers=auth(token),
                        json={"items": [{"title": "Attention is All You Need",
                                         "year": 2017}]})
        assert r.status_code == 200, r.text
        body = r.json()["results"][0]
        assert body["state"] == "verified"
        assert body["evidence"]["source"] == "local"

        r2 = client.post("/references/verify", headers=auth(token),
                         json={"items": [{"title": "完全编造的标题 XYZABC"}]})
        assert r2.status_code == 200
        # 离线态不判 fake：本地库未命中 ≠ 文献不存在（在线的「fake」需要三源交叉才有依据）
        row = r2.json()["results"][0]
        assert row["state"] == "unverified"
        assert row["evidence"]["source"] == "local"
