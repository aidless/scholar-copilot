"""图表渲染（v1.9 #3）：用 matplotlib 把结构化图表规格渲染成 PNG。

原产品图表只有 Mermaid（前端画、docx 里没有图）。这里在后端用 matplotlib（Agg
无头后端）把「柱状/折线/饼图」渲染成 PNG 字节，供 `/tools/chart` 直接返回或由
`docx_builder.add_chart_from_spec` 插入 DOCX。纯计算、零 IO 依赖（除字体探测）。
"""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")  # 无头后端，服务器环境必须
import matplotlib.pyplot as plt  # noqa: E402

# 中文字体：按可用性从优到劣挑选，避免「方块字」
_CJK_CANDIDATES = [
    "Noto Serif CJK SC", "Noto Sans CJK SC", "Source Han Sans SC",
    "Droid Sans Fallback", "WenQuanYi Zen Hei", "SimHei", "Microsoft YaHei",
]
matplotlib.rcParams["axes.unicode_minus"] = False
try:  # 只保留系统里真实存在的字体，避免 warning
    from matplotlib import font_manager as _fm
    _present = {f.name for f in _fm.fontManager.ttflist}
    _cjk = [n for n in _CJK_CANDIDATES if n in _present]
    if _cjk:
        matplotlib.rcParams["font.sans-serif"] = _cjk + ["DejaVu Sans"]
        matplotlib.rcParams["font.family"] = "sans-serif"
except Exception:  # 字体探测失败不致命
    pass

CHART_TYPES = ("bar", "line", "pie")


def available_types() -> list[str]:
    return list(CHART_TYPES)


def render_chart(spec: dict, dpi: int = 150) -> bytes:
    """把图表规格渲染成 PNG 字节。

    spec 形如：
      {"type": "bar", "title": "各章字数",
       "labels": ["绪论", "综述", "方法"],
       "series": [{"name": "字数", "values": [1200, 3400, 2100]}],
       "xlabel": "章节", "ylabel": "字数"}
    饼图只用第一组 series 的 values。
    """
    ctype = (spec or {}).get("type")
    if ctype not in CHART_TYPES:
        raise ValueError(f"不支持的图表类型：{ctype}；可选 {'/'.join(CHART_TYPES)}")
    labels = spec.get("labels") or []
    series = spec.get("series") or []
    if not labels or not series:
        raise ValueError("图表需要 labels 与非空 series")
    for s in series:
        vals = s.get("values") or []
        if len(vals) != len(labels):
            raise ValueError("series.values 长度必须与 labels 一致")
        if not all(isinstance(v, (int, float)) for v in vals):
            raise ValueError("series.values 必须全是数字")

    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=dpi)
    try:
        if ctype == "bar":
            n = len(series)
            width = 0.8 / max(n, 1)
            import numpy as np
            x = np.arange(len(labels))
            for i, s in enumerate(series):
                ax.bar(x + i * width - 0.4 + width / 2, s["values"],
                       width=width, label=s.get("name", f"系列{i + 1}"))
            ax.set_xticks(x)
            ax.set_xticklabels(labels)
            if n > 1:
                ax.legend()
        elif ctype == "line":
            for i, s in enumerate(series):
                ax.plot(labels, s["values"], marker="o",
                        label=s.get("name", f"系列{i + 1}"))
            if len(series) > 1:
                ax.legend()
        else:  # pie
            ax.pie(series[0]["values"], labels=labels, autopct="%1.1f%%")
        if spec.get("title"):
            ax.set_title(spec["title"])
        if ctype != "pie":
            if spec.get("xlabel"):
                ax.set_xlabel(spec["xlabel"])
            if spec.get("ylabel"):
                ax.set_ylabel(spec["ylabel"])
            ax.grid(True, linestyle="--", alpha=0.4)
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        return buf.getvalue()
    finally:
        plt.close(fig)
