"""v1.8 #7：引用格式导出（GB/T 7714 / APA / IEEE / BibTeX / RIS）。

纯函数断言逐字符检查输出，避免「看起来对」；端点层验证 404/409/422 与 Content-Disposition。
"""
import pytest
from fastapi.testclient import TestClient

from app.export import citation

PHONE = "13800000011"
PW = "Test123456"

ITEMS = [
    {"title": "Attention Is All You Need", "authors": "Ashish Vaswani; Noam Shazeer; Niki Parmar; Jakob Uszkoreit",
     "year": 2017, "doi": "10.5555/3295222", "url": None, "kind": "journal"},
    {"title": "深度学习综述", "authors": "张三；李四", "year": 2020, "doi": None,
     "url": "https://example.org/a", "kind": "web"},
]


def make_client():
    from app.main import create_app
    return TestClient(create_app())


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def register(client: TestClient, phone: str) -> str:
    r = client.post("/auth/register", json={"phone": phone, "password": PW, "check_code": "000000"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# ── 纯函数 ───────────────────────────────────────────────────

def test_gb7714_three_or_more_authors_uses_deng():
    text = citation.to_gb7714(ITEMS)
    lines = text.splitlines()
    # 4 位作者 → 前 3 + ", 等"
    assert lines[0].startswith("[1] Ashish Vaswani, Noam Shazeer, Niki Parmar, 等. Attention Is All You Need[J]")
    assert "2017" in lines[0]
    assert "DOI: 10.5555/3295222" in lines[0]
    # 中文两位作者全列 + [EB/OL]
    assert lines[1].startswith("[2] 张三, 李四. 深度学习综述[EB/OL]")
    assert "https://example.org/a" in lines[1]


def test_gb7714_two_authors_list_all():
    one = [{"title": "X", "authors": "A; B", "year": 2020, "kind": "journal"}]
    assert citation.to_gb7714(one).startswith("[1] A, B. X[J]")


def test_apa_format():
    text = citation.to_apa(ITEMS)
    lines = text.splitlines()
    assert lines[0].startswith("Vaswani, A., Shazeer, N., Parmar, N., & Uszkoreit, J. (2017). Attention Is All You Need.")
    assert lines[0].endswith("https://doi.org/10.5555/3295222")
    # 中文名原样保留
    assert lines[1].startswith("张三, 李四 (2020). 深度学习综述.")


def test_ieee_format():
    text = citation.to_ieee(ITEMS)
    lines = text.splitlines()
    assert lines[0].startswith('[1] A. Vaswani, N. Shazeer, N. Parmar and J. Uszkoreit, "Attention Is All You Need"')
    assert "doi: 10.5555/3295222" in lines[0]


def test_bibtex_format():
    text = citation.to_bibtex(ITEMS)
    assert text.startswith("@article{ref1_Attention2017,")
    assert "title = {Attention Is All You Need}" in text
    assert "author = {Ashish Vaswani and Noam Shazeer and Niki Parmar and Jakob Uszkoreit}" in text
    assert "doi = {10.5555/3295222}" in text
    # 第二条 web → @misc
    assert "@misc{" in text


def test_ris_format():
    text = citation.to_ris(ITEMS)
    assert text.startswith("TY  - JOUR")
    assert "TI  - Attention Is All You Need" in text
    assert text.count("AU  - ") == 6  # 4 + 2
    assert "ER  - " in text
    assert "TY  - ELEC" in text


def test_empty_authors_fallback():
    one = [{"title": "匿名报告", "authors": None, "year": None, "kind": "custom"}]
    assert "佚名" in citation.to_gb7714(one)
    assert "Anon." in citation.to_apa(one)
    assert "Anonymous" in citation.to_ieee(one)


def test_render_unknown_style_raises():
    with pytest.raises(KeyError):
        citation.render(ITEMS, "chicago")


def test_render_returns_media_and_ext():
    text, media, ext = citation.render(ITEMS, "bibtex")
    assert media.startswith("application/x-bibtex") and ext == "bib"
    text, media, ext = citation.render(ITEMS, "ris")
    assert "research-info-systems" in media and ext == "ris"


# ── 端点 ─────────────────────────────────────────────────────

def test_styles_endpoint_lists_five():
    client = make_client()
    r = client.get("/references/styles")
    assert r.status_code == 200
    assert set(r.json()["styles"]) == {"gb7714", "apa", "ieee", "bibtex", "ris"}


def test_export_refs_flow_and_idor():
    client = make_client()
    token = register(client, PHONE)
    order = client.post("/writing/orders",
                        json={"title": "引用格式导出测试", "education": "硕士", "word_count": 6000},
                        headers=auth(token)).json()
    oid = order["id"]
    # 未挂文献 → 409
    r = client.get(f"/references/orders/{oid}/export?style=gb7714", headers=auth(token))
    assert r.status_code == 409, r.text
    # 挂两条
    r = client.post(f"/references/orders/{oid}", json={"items": [
        {"title": "Attention Is All You Need", "authors": ["Vaswani", "Shazeer"],
         "year": 2017, "doi": "10.5555/3295222"},
        {"title": "深度学习综述", "authors": ["张三", "李四"], "year": 2020,
         "url": "https://example.org/a", "kind": "web"},
    ]}, headers=auth(token))
    assert r.status_code == 200, r.text
    # 五种格式都 200 且 Content-Disposition 带扩展名
    for style, ext in [("gb7714", "txt"), ("apa", "txt"), ("ieee", "txt"),
                       ("bibtex", "bib"), ("ris", "ris")]:
        r = client.get(f"/references/orders/{oid}/export?style={style}", headers=auth(token))
        assert r.status_code == 200, (style, r.text)
        assert f".{ext}" in r.headers["content-disposition"]
    # 未知格式 422
    r = client.get(f"/references/orders/{oid}/export?style=mla", headers=auth(token))
    assert r.status_code == 422
    # 别人的订单 → 404（IDOR）
    other = register(client, "13800000012")
    r = client.get(f"/references/orders/{oid}/export?style=gb7714", headers=auth(other))
    assert r.status_code == 404
