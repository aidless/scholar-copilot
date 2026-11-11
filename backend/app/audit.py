"""论文体检（review/audit）规则引擎：纯函数，不碰 DB、不发网络。

对照 review.py 里原来的 501 TODO：「引用核查 + 数字一致性 + AI 参与度标记复核」。

设计取舍：
- **不在这里重跑网络核查**（那是 POST /references/orders/{id}/verify 的活，会打 OpenAlex/Crossref）。
  本引擎只读库里已有的 verify_state，把「已查到的结论」汇总成报告，保证 audit 端点幂等、离线可跑。
- 所有规则都是**可解释的启发式**：命中即给「哪一章、哪句、什么规则」，不产出黑箱分数。
- 明确区分 severity：`fail` 只给「引用伪造 / 引用了不存在的编号」这类硬错误，
  其余一律 `warn`——因为启发式必然有误报，不能让误报阻断用户导出。
"""
from __future__ import annotations

import re

# 与 tools.py 的 AI 套话表保持同源语义，这里只取最能定性的少量高频词
_AI_CLICHE = [
    "综上所述", "总而言之", "值得注意的是", "不难发现", "毋庸置疑",
    "随着社会的发展", "在当今社会", "具有重要的理论意义和实践价值",
]

_PCT = re.compile(r"\d+(?:\.\d+)?\s*%")
_PVAL = re.compile(r"[pP]\s*(?:<|>|=|≤|≥)\s*0?\.\d+")
_SAMPLE = re.compile(r"[nN]\s*=\s*\d+")
_CITE = re.compile(r"\[(\d+)\]")
# 句子切分：句号/问号/叹号/分号（中文标点）
_SENT_SPLIT = re.compile(r"[。！？；;]")

_SEVERITY_ORDER = {"fail": 0, "warn": 1, "info": 2}


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text or "") if s.strip()]


def extract_numbers(text: str) -> list[dict]:
    """抽百分比 / p 值 / 样本量三类统计数字，带所在句。"""
    out = []
    for sent in split_sentences(text):
        for kind, pat in (("percent", _PCT), ("p_value", _PVAL), ("sample", _SAMPLE)):
            for m in pat.finditer(sent):
                out.append({"kind": kind, "raw": m.group(0).strip(), "sentence": sent})
    return out


def citation_markers(text: str) -> set[int]:
    return {int(n) for n in _CITE.findall(text or "")}


def _issue(rule: str, severity: str, detail: str, **loc) -> dict:
    return {"rule": rule, "severity": severity, "detail": detail, **loc}


def audit(chapters: list[dict], refs: list[dict],
          cliche_phrases: list[str] | None = None) -> dict:
    """chapters: [{node_id,title,content_md,word_count,ai_level,status}]
       refs:     [{id,title,verify_state,verify_evidence}]
    返回 {verdict, summary, issues}。
    """
    cliches = cliche_phrases or _AI_CLICHE
    issues: list[dict] = []
    done = [c for c in chapters if c.get("status") == "done"]
    full_text = "\n".join(c.get("content_md") or "" for c in done)

    # ── 规则 1：文献本身未通过核查 ──────────────────────────
    bad_refs = [r for r in refs if r.get("verify_state") in ("fake", "suspicious")]
    unverified_refs = [r for r in refs if r.get("verify_state") == "unverified"]
    for r in bad_refs:
        issues.append(_issue(
            "ref_invalid", "fail",
            f"文献判定为 {r['verify_state']}：「{r['title']}」", ref_id=r.get("id")))
    if unverified_refs:
        issues.append(_issue(
            "ref_unverified", "warn",
            f"{len(unverified_refs)} 条文献尚未核查，先调用 POST /references/orders/{{id}}/verify",
            count=len(unverified_refs)))

    # ── 规则 2/3：正文引用编号 ↔ 文献表对齐 ────────────────
    cited: set[int] = set()
    for c in done:
        cited |= citation_markers(c.get("content_md") or "")
    ref_count = len(refs)
    # 引用了不存在的编号（1-based）
    ghost = sorted(n for n in cited if n < 1 or n > ref_count)
    for n in ghost:
        issues.append(_issue(
            "cite_index_missing", "fail",
            f"正文出现 [{n}]，但文献表只有 {ref_count} 条", index=n))
    # 文献表里的编号从未在正文出现
    uncited_idx = [i for i in range(1, ref_count + 1) if i not in cited]
    if ref_count and uncited_idx:
        issues.append(_issue(
            "ref_uncited", "warn",
            f"{len(uncited_idx)} 条文献在正文中没有任何 [N] 引用：{uncited_idx}",
            indexes=uncited_idx))

    # ── 规则 4：统计数字裸奔（所在句无引用标记）────────────
    naked = []
    for c in done:
        for num in extract_numbers(c.get("content_md") or ""):
            if not _CITE.search(num["sentence"]):
                naked.append({"node_id": c.get("node_id"), "raw": num["raw"],
                              "kind": num["kind"], "sentence": num["sentence"][:120]})
    if naked:
        issues.append(_issue(
            "number_without_citation", "warn",
            f"{len(naked)} 处统计数字所在句没有引用标记（启发式，需人工判断）",
            samples=naked[:5], count=len(naked)))

    # ── 规则 5：AI 参与度标记与内容不符 ───────────────────
    # 标 C（人工撰写）却满是 AI 高频套话 → 标记可疑
    ai_mismatch = []
    for c in done:
        body = c.get("content_md") or ""
        if c.get("ai_level") == "C" and body:
            hits = sum(body.count(w) for w in cliches)
            if hits >= 3:
                ai_mismatch.append({"node_id": c.get("node_id"),
                                    "title": c.get("title"), "cliche_hits": hits})
    if ai_mismatch:
        issues.append(_issue(
            "ai_level_mismatch", "warn",
            f"{len(ai_mismatch)} 章标记为人工撰写(C)但含大量 AI 套话，建议复核标记",
            chapters=ai_mismatch))
    # 有内容却标 pending，或 done 但无内容
    for c in chapters:
        if c.get("status") == "done" and not (c.get("content_md") or "").strip():
            issues.append(_issue("chapter_empty", "warn",
                                 f"章节 {c.get('node_id')} 标 done 但内容为空",
                                 node_id=c.get("node_id")))

    # ── 规则 6：字数与字段不符（±20% 容差）───────────────
    for c in done:
        body = (c.get("content_md") or "").strip()
        declared = int(c.get("word_count") or 0)
        actual = len(re.sub(r"\s", "", body))
        if declared and actual and abs(actual - declared) / max(declared, 1) > 0.2:
            issues.append(_issue(
                "word_count_drift", "warn",
                f"章节 {c.get('node_id')} 声明 {declared} 字，实际 {actual} 字（偏差 >20%）",
                node_id=c.get("node_id"), declared=declared, actual=actual))

    # ── 汇总 ────────────────────────────────────────────
    issues.sort(key=lambda x: _SEVERITY_ORDER.get(x["severity"], 9))
    has_fail = any(i["severity"] == "fail" for i in issues)
    has_warn = any(i["severity"] == "warn" for i in issues)
    verdict = "fail" if has_fail else ("warn" if has_warn else "pass")
    return {
        "verdict": verdict,
        "summary": {
            "chapters_done": len(done),
            "chapters_total": len(chapters),
            "refs_total": ref_count,
            "refs_invalid": len(bad_refs),
            "refs_unverified": len(unverified_refs),
            "refs_uncited": len(uncited_idx),
            "cite_indexes_missing": len(ghost),
            "numbers_checked": sum(len(extract_numbers(c.get("content_md") or "")) for c in done),
            "numbers_without_citation": len(naked),
            "ai_level_mismatch": len(ai_mismatch),
            "issues_total": len(issues),
        },
        "issues": issues,
        "disclaimer": "启发式体检：数字裸奔/字数漂移/AI 标记为可疑提示，非学术不端认定；"
                      "文献真伪以 verify_state 为准。",
    }
