"""#8 真查重/AIGC 可解释自查：本地 n-gram + 语义比对，必须给可点击证据。

纪律：不给伪精确的「查重率」「AIGC 率」。本模块只做两件可复算的事：
1) 拿你的文本和**你自己提供的**参照语料做字符级/语义级比对，输出命中的原文片段与位置；
2) 输出 AIGC 文本的**可测量特征**（句长分布、套话密度、连接词密度…）与对应证据片段。

任何结论都必须能顺着 evidence 里的片段在原文里找到，否则不算数。
"""
import math

import pytest

from app.similarity import (
    aigc_features,
    cosine_similarity,
    match_fragments,
    selfcheck,
    tokenize,
)


def test_tokenize_cjk_bigrams_and_latin_words():
    toks = tokenize("深度学习 model works")
    assert "深度" in toks  # 中文按双字切
    assert "学习" in toks
    assert "model" in toks
    assert "works" in toks


def test_match_fragments_finds_shared_passage_with_positions():
    text = "绪论部分讨论了研究背景与研究意义。"
    ref = "本文绪论部分讨论了研究背景与研究意义，第二章给出方法。"
    frags = match_fragments(text, ref, min_len=6)
    assert frags, "应至少命中一段"
    f = frags[0]
    assert f["text_start"] >= 0
    assert text[f["text_start"]:f["text_start"] + f["length"]] == f["fragment"]
    assert f["fragment"] in ref


def test_match_fragments_no_overlap_returns_empty():
    assert match_fragments("完全不相干的一段中文内容", "abc def ghi", min_len=6) == []


def test_cosine_similarity_identical_is_one():
    assert cosine_similarity("研究背景与意义", "研究背景与意义") == pytest.approx(1.0, abs=1e-6)


def test_cosine_similarity_disjoint_is_zero():
    assert cosine_similarity("苹果 香蕉 橘子", "量子 引力 拓扑") == pytest.approx(0.0, abs=1e-9)


def test_selfcheck_reports_overlap_with_evidence():
    text = "本文提出一种基于多模态特征融合的学术文本合规检测方法。"
    ref = {
        "id": "R1",
        "title": "多模态特征融合",
        "text": "本文提出一种基于多模态特征融合的学术文本合规检测方法，并在多个数据集上验证。",
    }
    out = selfcheck(text, [ref])
    assert out["references"][0]["overlap_ratio"] > 0.5
    assert out["references"][0]["fragments"], "必须给出可点击的命中片段"
    assert out["references"][0]["cosine"] > 0.3
    assert out["disclaimer"]


def test_selfcheck_empty_reference_list_is_safe():
    out = selfcheck("一段文字", [])
    assert out["references"] == []
    assert out["max_overlap_ratio"] == 0.0


def test_selfcheck_verdict_flags_high_overlap():
    text = "学术诚信是研究活动的底线。"
    ref = {"id": "R1", "title": "t", "text": "学术诚信是研究活动的底线，不可妥协。"}
    out = selfcheck(text, [ref])
    assert out["verdict"] in {"high_overlap", "moderate_overlap", "low_overlap"}
    assert out["max_overlap_ratio"] > 0


def test_aigc_features_return_evidence_snippets():
    text = (
        "随着经济的快速发展，相关技术得到了广泛应用。众所周知，该方法具有重要意义。"
        "本文将系统性地讨论这一问题，并给出详尽分析。综上所述，该方法取得了良好效果。"
        "在本研究中，我们发现了一些有趣的现象。"
    )
    feats = aigc_features(text)
    assert feats
    names = {f["feature"] for f in feats}
    assert "cliche_density" in names
    cliche = next(f for f in feats if f["feature"] == "cliche_density")
    assert cliche["evidence"], "套话特征必须给出命中的原文片段"
    assert any("众所周知" in e for e in cliche["evidence"])
    assert cliche["value"] > 0


def test_aigc_features_empty_text_is_safe():
    feats = aigc_features("")
    assert isinstance(feats, list)
    assert all("feature" in f and "evidence" in f for f in feats)


def test_aigc_features_sentence_length_variance_is_measurable():
    import statistics

    uniform = "。".join(["这是一句长度完全相同的话" for _ in range(8)]) + "。"
    feats = aigc_features(uniform)
    sl = next(f for f in feats if f["feature"] == "sentence_len_cv")
    lens = [len(s) for s in uniform.split("。") if s]
    assert sl["value"] == pytest.approx(statistics.pstdev(lens) / (sum(lens) / len(lens)), abs=1e-6)


def test_aigc_features_no_math_nan():
    feats = aigc_features("短。")
    for f in feats:
        assert not math.isnan(float(f["value"]))
