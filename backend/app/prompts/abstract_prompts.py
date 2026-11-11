"""摘要生成 Prompt 模板（中/英双语）。

摘要不是「把正文头几段拼起来」——它要在一段里回答「做了什么、怎么做的、
结果如何、意义何在」。模板显式约束字数与结构，并禁止出现引用标号/图表编号
（摘要里不该有 [1] 或 表 2）。
"""

ABSTRACT_SYSTEM_ZH = """你是一位资深学术编辑。请为给定论文正文撰写中文摘要。

要求：
1. 一段式，200~350 字，不分点、不加小标题；
2. 依次交代：研究背景与问题、研究方法/技术路线、主要结果（尽量给出量化结论）、结论与意义；
3. 不得出现引用标号（如 [1]）、图表编号（如 图 2/表 1）、章节引用；
4. 不夸大、不编造正文没有的数据；
5. 只输出摘要正文本身，不要「摘要：」前缀。"""

ABSTRACT_SYSTEM_EN = """You are a senior academic editor. Write an English abstract for the given manuscript.

Rules:
1. One paragraph, 150-250 words, no bullets, no subheadings;
2. Cover in order: background & problem, methods/technical approach, key results (quantify where possible), conclusion & significance;
3. No citation markers (e.g. [1]), no figure/table numbers (e.g. Fig. 2 / Table 1), no section references;
4. Do not exaggerate or invent data not present in the text;
5. Output the abstract body only, without a leading "Abstract:"."""

# 关键词提取（摘要后附带 3~6 个关键词）
KEYWORDS_SYSTEM_ZH = """从给定摘要中提炼 3~6 个中文关键词，用「；」分隔，只输出关键词本身，不要编号或解释。"""


def build_abstract_user_prompt(title: str, body_md: str, max_chars: int = 6000) -> str:
    """把正文裁剪到 max_chars（摘要只需主干信息，避免超长 prompt）。"""
    body = body_md or ""
    if len(body) > max_chars:
        body = body[:max_chars] + "\n……（正文过长已截断）"
    return f"""论文题目：{title}

论文正文如下（Markdown）：

---
{body}
---

请据此撰写摘要。"""
