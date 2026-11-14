"""在线工具：降重/改写（LLM）+ 检测报告（启发式，诚实定性）。

检测纪律：启发式体检只报告可测量的文本特征，绝不输出「查重率/AIGC 率」
这类伪精确数字——原产品的检测产品线卖的就是不可证伪的数字。
"""
import re
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..llm.router import complete_for
from ..ratelimit import rate_limit_llm
from ..prompts.rewrite_prompts import REWRITE_SYSTEM_PROMPT, build_rewrite_user_prompt
from ..prompts.safety import wrap_untrusted
from ..prompts.diagram_prompts import DIAGRAM_SYSTEM_PROMPT, build_diagram_user_prompt
from ..prompts.ppt_prompts import PPT_SYSTEM_PROMPT, build_ppt_user_prompt
from ..export.pptx_builder import build_pptx, parse_ppt_spec
from ..similarity import aigc_features
from fastapi import Response
from urllib.parse import quote

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


@router.post("/rewrite", dependencies=[Depends(rate_limit_llm)])
async def rewrite(body: RewriteIn):
    """粘贴文本降重/改写（不落库）。"""
    result = await complete_for(
        "rewrite",
        build_rewrite_user_prompt(wrap_untrusted(body.text, "待改写正文"), body.instruction),
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


@router.post("/detect", dependencies=[Depends(rate_limit_llm)])
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
        "aigc_features": aigc_features(text),
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


class PptIn(BaseModel):
    topic: str = Field(min_length=2, max_length=200)
    audience: str = Field(default="学术评审", max_length=64)
    pages: int = Field(default=10, ge=4, le=20)
    wait: bool = True


@router.post("/ppt", dependencies=[Depends(rate_limit_llm)])
async def make_ppt(body: PptIn):
    """按主题生成 PPTX（LLM 出结构化大纲 → python-pptx 渲染，可编辑）。"""
    result = await complete_for(
        "ppt",
        build_ppt_user_prompt(body.topic, body.audience, body.pages),
        system=PPT_SYSTEM_PROMPT, max_tokens=2048,
    )
    try:
        spec = parse_ppt_spec(result.text)
    except ValueError as exc:
        raise HTTPException(502, f"大纲解析失败，请重试：{exc}") from None
    data = build_pptx(spec)
    fname = quote(f"{spec['title'][:40]}.pptx")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"},
    )


class DiagramIn(BaseModel):
    description: str = Field(min_length=4, max_length=2000)
    kind: str = Field(default="flowchart", pattern="^(flowchart|sequence|architecture)$")


@router.post("/diagram", dependencies=[Depends(rate_limit_llm)])
async def make_diagram(body: DiagramIn):
    """自然语言 → Mermaid 代码（前端自行渲染；不返回图片，避免黑盒）。"""
    result = await complete_for(
        "diagram",
        build_diagram_user_prompt(wrap_untrusted(body.description, "图表描述"), body.kind),
        system=DIAGRAM_SYSTEM_PROMPT, max_tokens=1200,
    )
    text = result.text.strip()
    m = re.search(r"```mermaid\s*(.+?)```", text, re.S)
    code = (m.group(1) if m else text).strip()
    if not re.search(r"^(flowchart|graph|sequenceDiagram|classDiagram)", code):
        raise HTTPException(502, "模型未返回合法 Mermaid 代码，请重试或换个描述")
    return {"mermaid": code, "kind": body.kind, "model": result.model,
            "tokens_in": result.prompt_tokens, "tokens_out": result.completion_tokens}


# ── 图表渲染（v1.9 #3）──────────────────────────────────────────────
from typing import Any  # noqa: E402
from ..export.charts import available_types, render_chart  # noqa: E402


class ChartSeries(BaseModel):
    name: str = Field(default="", max_length=64)
    values: list[float] = Field(min_length=1)


class ChartIn(BaseModel):
    type: str = Field(max_length=16)
    title: str = Field(default="", max_length=200)
    labels: list[str] = Field(min_length=1)
    series: list[ChartSeries] = Field(min_length=1)
    xlabel: str = Field(default="", max_length=64)
    ylabel: str = Field(default="", max_length=64)


@router.get("/chart/types")
async def chart_types():
    return {"types": available_types()}


@router.post("/chart")
async def chart(body: ChartIn):
    """把结构化图表规格渲染成 PNG（matplotlib 无头后端）。"""
    spec: dict[str, Any] = body.model_dump()
    try:
        png = render_chart(spec)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return Response(content=png, media_type="image/png",
                    headers={"Content-Disposition": "inline; filename=chart.png"})


# ── 数据分析 / 问卷统计（v1.9 #9）────────────────────────────────────
from ..analysis import analyze as _analyze_stats  # noqa: E402


class StatsIn(BaseModel):
    columns: list[str] = Field(min_length=1, max_length=200)
    rows: list[list[Any]] = Field(min_length=1, max_length=50_000)
    categorical: list[str] = Field(default_factory=list)


@router.post("/stats")
async def stats(body: StatsIn):
    """对一份表格做描述统计 + 两两 Pearson 相关 + 类别频数分布（纯计算）。"""
    try:
        return _analyze_stats(body.columns, body.rows, body.categorical)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


# ── 多模型路由与成本对比（v1.11 #22）─────────────────────────────────
from ..llm.router import estimate_cost, routing_table  # noqa: E402


@router.get("/models")
async def models():
    """当前路由表（任务 → 模型链）+ 成本表，供前端展示与人工选择。"""
    return routing_table()


class CostCompareIn(BaseModel):
    task: str = Field(default="default", max_length=32)
    tokens_in: int = Field(ge=0, le=10_000_000)
    tokens_out: int = Field(ge=0, le=10_000_000)


@router.post("/models/cost")
async def models_cost(body: CostCompareIn):
    """同一 token 用量下，各候选模型的预估成本（元）对比。"""
    from ..llm.router import routes_for
    rows = [{"model": m, "cost_cny": estimate_cost(m, body.tokens_in, body.tokens_out)}
            for m in routes_for(body.task)]
    rows.sort(key=lambda r: r["cost_cny"])
    return {"task": body.task, "tokens_in": body.tokens_in,
            "tokens_out": body.tokens_out, "options": rows}


# ── 真查重/AIGC 可解释自查（v1.12 #8）───────────────────────────────
from ..similarity import aigc_features, selfcheck  # noqa: E402


class SelfCheckRef(BaseModel):
    id: str = Field(max_length=64)
    title: str = Field(default="", max_length=500)
    text: str = Field(min_length=1, max_length=200_000)


class SelfCheckIn(BaseModel):
    text: str = Field(min_length=20, max_length=200_000)
    references: list[SelfCheckRef] = Field(min_length=1, max_length=100)


@router.post("/selfcheck")
async def selfcheck_endpoint(body: SelfCheckIn):
    """本地重合度自查：与**你提供的**参照语料比对，逐条给可点击的命中片段。

    不是查重率、不是 AIGC 鉴定——结论必须能顺着 evidence 回到原文。
    """
    return selfcheck(body.text, [r.model_dump() for r in body.references])


class AigcFeatureIn(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)


@router.post("/aigc-features")
async def aigc_features_endpoint(body: AigcFeatureIn):
    """AIGC 文本的可测量特征（句长变异、套话密度、连接词密度…），每条带原文证据。"""
    return {"features": aigc_features(body.text),
            "disclaimer": "特征描述「文本长得像不像模型写的」，不是 AIGC 鉴定结论。"}
