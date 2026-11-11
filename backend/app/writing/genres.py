"""写作文体（writing_type）注册表。

不同文体共用一套生成/导出管线，但大纲结构与行文要求不同：毕业论文重「绪论→
理论→方法→实验→结论」，文献综述重「检索策略→主题聚类→研究空白→展望」，
开题报告重「选题依据→研究方案→可行性→进度安排」。这里只放「给模型的结构指引」，
不写死章节标题，避免把某种格式套死到所有学校。
"""
from __future__ import annotations

DEFAULT_WRITING_TYPE = "thesis"

GENRES: dict[str, dict[str, str]] = {
    "thesis": {
        "label": "毕业论文",
        "outline_hint": (
            "按「绪论 → 相关理论与技术基础 → 研究/设计方法 → 实验与分析 → "
            "结论与展望」的主线组织，突出研究问题、方法创新与实验验证。"
        ),
        "writing_hint": "学术规范、论证严密，方法与实验结果要可复现，避免空泛综述。",
    },
    "literature_review": {
        "label": "文献综述",
        "outline_hint": (
            "按「检索策略与文献来源 → 研究主题聚类与脉络梳理 → 代表性成果比较 → "
            "研究空白与争议 → 未来展望」组织，强调横向对比与批判性评价，而非罗列。"
        ),
        "writing_hint": "以主题而非时间线组织文献；每段落点是对比、评价与 gap，不做流水账。",
    },
    "proposal": {
        "label": "开题报告",
        "outline_hint": (
            "按「选题背景与意义 → 国内外研究现状 → 研究内容与目标 → 研究方法与技术路线 → "
            "可行性分析 → 进度安排与预期成果」组织。"
        ),
        "writing_hint": "强调「要做什么、为什么能做、怎么做、何时完成」，技术路线要具体。",
    },
    "journal_article": {
        "label": "期刊论文",
        "outline_hint": (
            "按「引言 → 相关工作 → 方法 → 实验 → 讨论 → 结论」组织，篇幅紧凑、"
            "强调贡献点与可复现实验。"
        ),
        "writing_hint": "开门见山讲贡献；实验部分要给出设置、指标与对比基线。",
    },
    "task_book": {
        "label": "任务书",
        "outline_hint": (
            "按「课题名称与来源 → 研究目的与任务 → 主要研究内容 → 技术要求与指标 → "
            "进度计划 → 参考文献」组织，条目化、指标可量化。"
        ),
        "writing_hint": "条目化表述，技术指标与交付物明确可验收。",
    },
    "course_paper": {
        "label": "课程论文",
        "outline_hint": (
            "按「引言 → 理论基础 → 分析与论证 → 案例/应用 → 结论」组织，篇幅适中，"
            "重在概念清晰与论证完整。"
        ),
        "writing_hint": "概念解释清楚，论证有据，可结合课程知识做应用分析。",
    },
}


def is_valid(writing_type: str) -> bool:
    return writing_type in GENRES


def label_of(writing_type: str) -> str:
    return GENRES.get(writing_type, GENRES[DEFAULT_WRITING_TYPE])["label"]


def outline_hint(writing_type: str) -> str:
    return GENRES.get(writing_type, GENRES[DEFAULT_WRITING_TYPE])["outline_hint"]
