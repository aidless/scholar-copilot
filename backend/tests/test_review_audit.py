"""v1.8 #1：review/audit 规则引擎（纯函数）+ 端点。

RED 原则：每条规则都构造「明确违规」的输入并断言被检出。
"""
import pytest
from fastapi.testclient import TestClient

from app.audit import audit, citation_markers, extract_numbers

PHONE = "13800000011"
PW = "Test123456"


def chapter(node, content, word_count=100, ai="A", status="done", title=None):
    return {"node_id": node, "title": title or node, "content_md": content,
            "word_count": word_count, "ai_level": ai, "status": status}


def ref(i, state="verified", title=None):
    return {"id": f"r{i}", "title": title or f"文献{i}", "verify_state": state,
            "verify_evidence": {}}


# ── 纯函数 ───────────────────────────────────────────────────

def test_extract_numbers_three_kinds():
    text = "准确率达到 95.3%，p<0.05，样本量 n=320。"
    kinds = {n["kind"] for n in extract_numbers(text)}
    assert kinds == {"percent", "p_value", "sample"}
    raw = {n["raw"] for n in extract_numbers(text)}
    assert "95.3%" in raw and "n=320" in raw


def test_citation_markers_dedup():
    assert citation_markers("见 [1]，另见 [2] 与 [1]。") == {1, 2}
    assert citation_markers("无引用") == set()


def test_rule_ref_invalid_is_fail():
    report = audit([chapter("ch1", "正文。")], [ref(1, "fake", "编造的文献")])
    assert report["verdict"] == "fail"
    assert any(i["rule"] == "ref_invalid" and i["severity"] == "fail" for i in report["issues"])


def test_rule_cite_index_missing_is_fail():
    # 正文引用 [3]，但只有 1 条文献 → 硬错误
    report = audit([chapter("ch1", "结论见 [3]。")], [ref(1)])
    assert report["verdict"] == "fail"
    hit = [i for i in report["issues"] if i["rule"] == "cite_index_missing"]
    assert hit and hit[0]["index"] == 3


def test_rule_ref_uncited_warn():
    report = audit([chapter("ch1", "正文没有引用标记。")], [ref(1), ref(2)])
    hit = [i for i in report["issues"] if i["rule"] == "ref_uncited"]
    assert hit and hit[0]["indexes"] == [1, 2]
    assert report["verdict"] == "warn"


def test_rule_number_without_citation():
    body = "模型准确率达到 91.2%，效果显著。"
    report = audit([chapter("ch1", body)], [])
    hit = [i for i in report["issues"] if i["rule"] == "number_without_citation"]
    assert hit and hit[0]["count"] >= 1


def test_rule_number_with_citation_not_flagged():
    body = "模型准确率达到 91.2%[1]，效果显著。"
    report = audit([chapter("ch1", body)], [ref(1)])
    assert not [i for i in report["issues"] if i["rule"] == "number_without_citation"]


def test_rule_ai_level_mismatch():
    body = "综上所述，总而言之，值得注意的是，不难发现，毋庸置疑，本研究很重要。"
    report = audit([chapter("ch1", body, ai="C")], [])
    hit = [i for i in report["issues"] if i["rule"] == "ai_level_mismatch"]
    assert hit and hit[0]["chapters"][0]["cliche_hits"] >= 3


def test_rule_word_count_drift():
    body = "短" * 10  # 实际 10 字，声明 100 字 → 偏差 90%
    report = audit([chapter("ch1", body, word_count=100)], [])
    hit = [i for i in report["issues"] if i["rule"] == "word_count_drift"]
    assert hit and hit[0]["declared"] == 100 and hit[0]["actual"] == 10


def test_rule_chapter_empty_done():
    report = audit([chapter("ch1", "   ", word_count=0)], [])
    assert any(i["rule"] == "chapter_empty" for i in report["issues"])


def test_clean_paper_passes():
    body = "准确率达到 91.2%[1]，与前人一致[1]。"
    report = audit([chapter("ch1", body, word_count=20, ai="A")], [ref(1)])
    assert report["verdict"] == "pass", report["issues"]
    assert report["summary"]["issues_total"] == 0


# ── 端点 ─────────────────────────────────────────────────────

def make_client():
    from app.main import create_app
    return TestClient(create_app())


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def register(client, phone):
    r = client.post("/auth/register", json={"phone": phone, "password": PW, "check_code": "000000"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_audit_endpoint_flow_and_idor():
    client = make_client()
    tok = register(client, PHONE)
    oid = client.post("/writing/orders", json={"title": "体检测试", "education": "硕士",
                                               "word_count": 6000}, headers=auth(tok)).json()["id"]
    client.post(f"/references/orders/{oid}", json={"items": [
        {"title": "Attention Is All You Need", "authors": ["Vaswani"], "year": 2017},
    ]}, headers=auth(tok))
    # 还没有章节 → 空体检（pass，因为无 fail 规则）
    r = client.post(f"/review/orders/{oid}/audit", headers=auth(tok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["order_id"] == oid
    assert body["verdict"] in ("pass", "warn", "fail")
    assert "summary" in body and "issues" in body
    # 文献未核查 → ref_unverified 警告
    assert any(i["rule"] == "ref_unverified" for i in body["issues"])
    # 只筛某条规则
    r = client.post(f"/review/orders/{oid}/audit?only=ref_unverified", headers=auth(tok))
    assert all(i["rule"] == "ref_unverified" for i in r.json()["issues"])
    # summary 轻量版
    r = client.get(f"/review/orders/{oid}/audit/summary", headers=auth(tok))
    assert r.status_code == 200 and "verdict" in r.json()
    # 别人的订单 → 404
    other = register(client, "13800000012")
    assert client.post(f"/review/orders/{oid}/audit", headers=auth(other)).status_code == 404
