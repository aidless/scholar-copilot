"""在线工具：降重/改写（LLM）+ 检测报告（启发式，诚实定性）。

检测纪律：启发式体检只报告可测量的文本特征，绝不输出「查重率/AIGC 率」
这类伪精确数字——原产品的检测产品线卖的就是不可证伪的数字。
"""
import re
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..db import get_db
from ..llm.registry import get_provider
from ..prompts.rewrite_prompts import REWRITE_SYSTEM_PROMPT, build_rewrite_user_prompt

router = APIRouter(prefix="/tools", tags=["tools"])

# 原产品 prompt 明令禁止、AI 生成文本高频出现的套话（chapter_prompts.py 的禁用清单 + 扩充）
AI_CLICHE_PHRASES = [
    "具有重要意义", "取得了良好效果", "得到了广泛应用", "综上所述", "综上所述，",
    "随着...的发展", "随着经济的快速发展", "不言而喻", "众所周知",
    "本文将", "本研究旨在", "为后续研究提供参考", "综上所述可知",
    "总而言之", "在一定程度上", "起到了至关重要的作用", "奠定了坚实基础",
]


class RewriteIn(BaseModel):
    text: str = Field(min_length=10, max_length=50_000)
    instruction: str = Field(default="", max_length=500)


@router.post("/rewrite")
async def rewrite(body: RewriteIn):
    """粘贴文本降重/改写（不落库）。"""
    provider = get_provider()
    result = await provider.complete(
        build_rewrite_user_prompt(body.text, body.instruction),
        system=REWRITE_SYSTEM_PROMPT, max_tokens=8192,
    )
    return {
        "text": result.text,
        "model": result.model,
        "tokens_in": result.prompt_tokens,
        "tokens_out": result.completion_tokens,
    }


class DetectIn(BaseModel):
    text: str = Field(min_length=10, max_length=200_000)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"[。！？；\n]+", text) if s.strip()]


def _top_repeats(text: str, n: int = 8, k: int = 3) -> list[dict]:
    """top-k 重复 n-gram（CJK 连续串），检测车轱辘话。"""
    compact = re.sub(r"\s", "", text)
    grams = Counter(compact[i:i + n] for i in range(len(compact) - n + 1))
    return [{"gram": g, "count": c}
            for g, c in grams.most_common(60) if c > 1][:k]


@router.post("/detect")
async def detect(body: DetectIn):
    """文本体检：可测量特征 + 启发式提示。非查重、非 AIGC 检测，结论仅供参考。"""
    text = body.text
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    sents = _sentences(text)
    sent_lens = [len(re.sub(r"\s", "", s)) for s in sents]
    avg_sent = round(sum(sent_lens) / len(sent_lens), 1) if sent_lens else 0

    cliche_hits = {p: text.count(p.replace("...", "")) for p in AI_CLICHE_PHRASES
                   if text.count(p.replace("...", "")) > 0}
    citations = re.findall(r"\[\d+(?:[-,，]\d+)*\]", text)
    repeats = _top_repeats(text)

    per_k = lambda c: round(c / max(cjk_chars, 1) * 1000, 1)  # noqa: E731

    report = {
        "metrics": {
            "cjk_chars": cjk_chars,
            "sentences": len(sents),
            "avg_sentence_len": avg_sent,
            "long_sentences": sum(1 for l in sent_lens if l > 120),
            "citation_markers": len(citations),
            "citations_per_1000": per_k(len(citations)),
            "has_table": "|" in text and "---" in text,
        },
        "cliche": {"hits": cliche_hits, "per_1000": per_k(sum(cliche_hits.values()))},
        "repeats": repeats,
        "advice": [],
        "disclaimer": "启发式体检，非查重率/AIGC 检测率；数字仅描述文本特征，不作合规结论。",
    }

    if cliche_hits:
        report["advice"].append(f"检测到 {len(cliche_hits)} 类 AI 高频套话（密度 {report['cliche']['per_1000']}/千字），建议改写为具体数据或功能描述")
    if len(citations) == 0:
        report["advice"].append("未检测到 [N] 引用标记；学术文本建议每章 3~5 处规范引用")
    if report["metrics"]["long_sentences"] > 3:
        report["advice"].append(f"{report['metrics']['long_sentences']} 个超长句（>120 字），建议拆分")
    if repeats:
        report["advice"].append(f"发现重复片段（如「{repeats[0]['gram'][:12]}…」×{repeats[0]['count']}），建议改写车轱辘话")
    return report
