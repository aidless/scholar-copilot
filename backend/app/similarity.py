"""#8 真查重/AIGC 可解释自查：本地 n-gram + 语义比对，必须给可点击证据。

纪律：不给伪精确的「查重率」「AIGC 率」。本模块只做两件可复算的事：
1) 拿你的文本和**你自己提供的**参照语料做片段级/向量级比对，输出命中的原文片段与位置；
2) 输出 AIGC 文本的**可测量特征**（句长变异、套话密度、连接词密度…）与对应证据片段。

任何结论都必须能顺着 evidence 里的片段在原文里找到，否则不算数。
"""
from __future__ import annotations

import math
import re
from collections import Counter

# AI 生成文本高频套话（与 routers/tools.py::AI_CLICHE_PHRASES 同源，此处用于特征提取）
CLICHE_PHRASES = [
    "具有重要意义", "取得了良好效果", "得到了广泛应用", "综上所述", "不言而喻", "众所周知",
    "本文将", "本研究旨在", "为后续研究提供参考", "总而言之", "在一定程度上",
    "起到了至关重要的作用", "奠定了坚实基础", "随着经济的快速发展", "随着...的发展",
    "值得注意的是", "在当今社会", "为了更好地", "本文首先", "本文其次", "本文最后",
    "总而言之", "综上所述可知",
]

# 连接词/过渡词（AI 文本的典型「连接词密集」特征）
CONNECTIVES = [
    "首先", "其次", "再次", "最后", "然而", "因此", "从而", "此外", "综上",
    "一方面", "另一方面", "换言之", "也就是说", "需要指出的是", "值得注意的是",
]

_CJK = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]+")


def tokenize(text: str) -> list[str]:
    """切词：CJK 取二元组（不依赖分词库，行为可复算），拉丁取单词。"""
    toks: list[str] = []
    cjk_runs = re.findall(r"[\u4e00-\u9fff]+", text)
    for run in cjk_runs:
        if len(run) == 1:
            toks.append(run)
        for i in range(len(run) - 1):
            toks.append(run[i:i + 2])
    toks.extend(w.lower() for w in _LATIN.findall(text))
    return toks


def cosine_similarity(a: str, b: str) -> float:
    """基于词频向量的余弦相似度（0~1）。"""
    ta, tb = Counter(tokenize(a)), Counter(tokenize(b))
    if not ta or not tb:
        return 0.0
    common = set(ta) & set(tb)
    num = sum(ta[t] * tb[t] for t in common)
    na = math.sqrt(sum(v * v for v in ta.values()))
    nb = math.sqrt(sum(v * v for v in tb.values()))
    if na == 0 or nb == 0:
        return 0.0
    return num / (na * nb)


def _segments(text: str, size: int = 20) -> list[tuple[int, str]]:
    """把文本按固定长度切成带位置的片段（位置用于回链原文）。"""
    compact = re.sub(r"\s", "", text)
    return [(i, compact[i:i + size]) for i in range(0, max(len(compact) - size + 1, 1))]


def match_fragments(text: str, reference: str, min_len: int = 20) -> list[dict]:
    """在 text 中找出与 reference 连续重合的片段。

    返回每条：`{fragment, text_start, length, ref_start}`；`text_start` 是**去空白后**的偏移，
    调用方若需在原文定位，应同样去空白后映射。
    """
    if not text or not reference:
        return []
    ref_compact = re.sub(r"\s", "", reference)
    text_compact = re.sub(r"\s", "", text)
    out: list[dict] = []
    seen: set[tuple[int, str]] = set()
    step = max(min_len // 2, 1)
    for start in range(0, max(len(text_compact) - min_len + 1, 1), step):
        window = text_compact[start:start + min_len]
        if len(window) < min_len:
            break
        pos = ref_compact.find(window)
        if pos < 0:
            continue
        # 向两侧扩展到最大连续重合
        left = 0
        while (start - left - 1 >= 0 and pos - left - 1 >= 0
               and text_compact[start - left - 1] == ref_compact[pos - left - 1]):
            left += 1
        right = min_len
        while (start + right < len(text_compact) and pos + right < len(ref_compact)
               and text_compact[start + right] == ref_compact[pos + right]):
            right += 1
        frag_start = start - left
        frag = text_compact[frag_start:frag_start + right]
        key = (frag_start, frag)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "fragment": frag,
            "text_start": frag_start,
            "length": len(frag),
            "ref_start": pos - left,
        })
    # 合并重叠片段，保留最长的若干条
    out.sort(key=lambda d: (-d["length"], d["text_start"]))
    merged: list[dict] = []
    for f in out:
        if any(not (f["text_start"] + f["length"] <= m["text_start"]
                    or m["text_start"] + m["length"] <= f["text_start"])
               for m in merged):
            continue
        merged.append(f)
    merged.sort(key=lambda d: d["text_start"])
    return merged[:10]


def selfcheck(text: str, references: list[dict]) -> dict:
    """本地自查：与给定参照语料比对，给出逐条证据与整体判定。

    references 每项：`{id, title, text}`。

    片段最小长度按文本长度自适应：短文本也允许命中（否则 13 字的文本永远命中不了 20 字窗口）。
    """
    results = []
    max_ratio = 0.0
    compact_len = max(len(re.sub(r"\s", "", text)), 1)
    for ref in references:
        ref_text = ref.get("text") or ""
        ref_len = len(re.sub(r"\s", "", ref_text))
        eff_min = min(20, max(8, min(compact_len, ref_len) // 2))
        frags = match_fragments(text, ref_text, min_len=eff_min)
        # 重合字符数（按片段去重后的覆盖长度）
        covered = 0
        spans = sorted((f["text_start"], f["text_start"] + f["length"]) for f in frags)
        cur_end = -1
        for s, e in spans:
            if s > cur_end:
                covered += e - s
                cur_end = e
            else:
                covered += e - max(s, cur_end)
                cur_end = max(cur_end, e)
        ratio = round(covered / compact_len, 4)
        cos = round(cosine_similarity(text, ref_text), 4)
        max_ratio = max(max_ratio, ratio)
        results.append({
            "id": ref.get("id"),
            "title": ref.get("title"),
            "overlap_ratio": ratio,
            "overlap_chars": covered,
            "cosine": cos,
            "fragments": frags,
        })
    results.sort(key=lambda d: (-d["overlap_ratio"], -d["cosine"]))
    if max_ratio >= 0.3:
        verdict = "high_overlap"
    elif max_ratio >= 0.1:
        verdict = "moderate_overlap"
    else:
        verdict = "low_overlap"
    return {
        "verdict": verdict,
        "max_overlap_ratio": max_ratio,
        "references": results,
        "disclaimer": (
            "本结果是你提供的参照语料与待检文本的**本地**重合度，"
            "既不是知网/维普查重率，也不是 AIGC 鉴定结论；"
            "重合度高只说明与该语料雷同，必须自行核对原文确认。"
        ),
    }


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"[。！？；\n]+", text) if s.strip()]


def aigc_features(text: str) -> list[dict]:
    """AIGC 文本的**可测量特征**，每条特征都带原文证据片段。

    这里描述的是「这段文本长得像不像模型写的」，不是鉴定结论。
    """
    feats: list[dict] = []
    compact_len = max(len(re.sub(r"\s", "", text)), 1)
    sents = _sentences(text)
    lens = [len(re.sub(r"\s", "", s)) for s in sents]

    # 1) 套话密度
    cliche_hits: list[str] = []
    for p in CLICHE_PHRASES:
        key = p.replace("...", "")
        cnt = text.count(key)
        if cnt:
            cliche_hits.append(f"{key}×{cnt}")
    feats.append({
        "feature": "cliche_density",
        "label": "AI 高频套话密度",
        "value": round(len(cliche_hits) / compact_len * 1000, 2),
        "unit": "处/千字",
        "evidence": [p for p in CLICHE_PHRASES
                     if p.replace("...", "") in text][:5],
        "detail": cliche_hits,
    })

    # 2) 句长变异系数（AI 文本通常句长过于均匀）
    if len(lens) >= 2:
        mean = sum(lens) / len(lens)
        var = sum((x - mean) ** 2 for x in lens) / len(lens)
        cv = math.sqrt(var) / mean if mean else 0.0
    else:
        mean = float(lens[0]) if lens else 0.0
        cv = 0.0
    feats.append({
        "feature": "sentence_len_cv",
        "label": "句长变异系数",
        "value": round(cv, 4),
        "unit": "变异系数",
        "evidence": [s[:40] for s in sents[:3]],
        "detail": {"sentences": len(lens), "mean_len": round(mean, 2)},
    })

    # 3) 连接词密度
    conn_hits = [c for c in CONNECTIVES if c in text]
    feats.append({
        "feature": "connective_density",
        "label": "连接词/过渡词密度",
        "value": round(len(conn_hits) / compact_len * 1000, 2),
        "unit": "处/千字",
        "evidence": conn_hits[:5],
        "detail": {"count": len(conn_hits)},
    })

    # 4) 平均句长
    feats.append({
        "feature": "avg_sentence_len",
        "label": "平均句长",
        "value": round(mean, 2),
        "unit": "字/句",
        "evidence": [s[:40] for s in sents[:3]],
        "detail": {"sentences": len(lens)},
    })

    # 5) 段落标记（Markdown 小标题/列表密度——模型爱用结构化排版）
    md = len(re.findall(r"^\s*(#{1,6}\s|[-*]\s|\d+[.、]\s)", text, flags=re.M))
    feats.append({
        "feature": "structure_marker_density",
        "label": "结构化排版标记密度",
        "value": round(md / compact_len * 1000, 2),
        "unit": "处/千字",
        "evidence": [ln[:40] for ln in text.splitlines() if re.match(
            r"^\s*(#{1,6}\s|[-*]\s|\d+[.、]\s)", ln)][:5],
        "detail": {"count": md},
    })

    return feats
