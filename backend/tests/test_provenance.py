"""#19 内容指纹链：A/B/C 参与度必须可审计——生成时记 sha256，改稿留链。

纪律：AI 参与度是「自证」的东西，所以必须有**不可篡改的指纹链**：
生成时记 sha256(chapter)，每次人工改稿再记一条 sha256(new)，
「改稿后指纹变了 → A 升 B」这件事本身就是证据。
"""
import hashlib

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.provenance import fingerprint, diff_ratio, chain_for_order

client = TestClient(create_app())


def test_fingerprint_is_sha256_of_normalized_text():
    a = fingerprint("  你好\n世界  ")
    b = fingerprint("你好世界")
    assert a == b, "指纹应对空白不敏感，否则换个空格就算改稿"
    assert len(a) == 64
    assert a == hashlib.sha256("你好世界".encode()).hexdigest()


def test_fingerprint_changes_with_content():
    assert fingerprint("内容A") != fingerprint("内容B")


def test_diff_ratio_identical_is_one():
    assert diff_ratio("完全一样的内容", "完全一样的内容") == pytest.approx(1.0, abs=1e-6)


def test_diff_ratio_disjoint_is_zero():
    assert diff_ratio("苹果香蕉", "量子引力") == pytest.approx(0.0, abs=1e-9)


def test_diff_ratio_partial():
    r = diff_ratio("前半部分完全一样后半不同", "前半部分完全一样后半也不同")
    assert 0.3 < r < 1.0


def test_chain_records_generate_then_edit():
    from app.db import get_session_factory
    import asyncio

    async def scenario():
        factory = get_session_factory()
        async with factory() as session:
            from app.provenance import record_event
            await record_event(session, tenant_id="t1", order_id="o1", node_id="ch1",
                               kind="generate", content="原始生成内容",
                               ai_level="A", job_id="j1")
            await record_event(session, tenant_id="t1", order_id="o1", node_id="ch1",
                               kind="edit", content="原始生成内容改了一点点",
                               ai_level="B", prev_content="原始生成内容")
            await session.commit()
            chain = await chain_for_order(session, "o1")
            return chain

    chain = asyncio.run(scenario())
    assert len(chain) == 2
    assert chain[0]["kind"] == "generate"
    assert chain[0]["content_sha256"] == fingerprint("原始生成内容")
    assert chain[0]["similarity"] is None
    assert chain[1]["kind"] == "edit"
    assert chain[1]["ai_level"] == "B"
    assert chain[1]["similarity"] < 1.0, "改稿后应能算出与原稿的相似度"
    assert chain[1]["similarity"] > 0.5
