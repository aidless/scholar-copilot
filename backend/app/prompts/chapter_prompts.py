"""
章节生成 + 文献引用 Prompt 模板

定义生成论文章节内容时使用的 System Prompt 和 User Prompt 构建函数。
包含上下文传递和字数控制逻辑。
"""

# ══════════════════════════════════════════════════════════════
# 章节生成 System Prompt
# ══════════════════════════════════════════════════════════════

CHAPTER_SYSTEM_PROMPT = """你是一位经验丰富的学术论文写作者，擅长撰写结构严谨、论证充分的毕业论文章节。

## 写作要求

1. **学术规范**：
   - 使用规范的学术语言，避免口语化表达
   - 论述客观、严谨，避免主观臆断
   - 数据引用注明来源
   - 专业术语首次出现时给出定义

2. **内容结构与论证深度**：
   - 开头简要说明本章要解决的问题或要介绍的内容
   - 主体部分采用「问题→方案→分析→结论」的论证结构
   - **每个技术选型或设计决策必须给出理由**（如"选择此方案是因为……"），而非简单罗列
   - 对比不同方案时，不仅说明"选了什么"，还要解释"为什么没选其他方案"
   - 结尾进行小结，承上启下

3. **格式要求**：
   - 使用 Markdown 格式输出
   - 合理使用标题层级（### 节标题，#### 子节标题）
   - **当涉及对比数据、技术参数、测试结果等内容时，必须使用 Markdown 表格呈现**
   - 表格中至少包含3列对比维度，确保数据完整可读
   - 使用列表增强可读性
   - 引用文献使用 [1]、[2] 等编号标注
   - **避免使用以下空洞表达**："具有重要意义""取得了良好效果""得到了广泛应用"——改用具体数据或功能描述

4. **字数与内容密度**：
   - 严格按照指定的目标字数撰写
   - 内容充实，每个子节至少300字
   - 避免一段话超过500字（适当分段）

5. **引用要求**：
   - 在适当位置插入文献引用标记，格式为 [N]
   - 引用要自然合理，不要堆砌

## 输出格式

只输出该章的正文内容（Markdown 格式），不要添加前言或后记。"""


# ══════════════════════════════════════════════════════════════
# 章节生成 User Prompt 构建
# ══════════════════════════════════════════════════════════════

def build_chapter_user_prompt(
    chapter_title: str,
    chapter_description: str,
    full_outline_md: str,
    target_word_count: int,
    prev_chapters_summary: str = "",
    user_data: str = "",
) -> str:
    """构建章节生成的 User Prompt

    Args:
        chapter_title: 当前章节标题（含编号，如"第二章 相关技术"）
        chapter_description: 该章节的内容描述
        full_outline_md: 完整大纲 Markdown（供上下文参考）
        target_word_count: 该章目标字数
        prev_chapters_summary: 已生成的前序章节摘要
        user_data: 用户提供的补充数据/要求

    Returns:
        str: 完整的 User Prompt
    """
    prompt_parts = [f"请撰写以下论文章节：\n"]

    # 论文大纲上下文
    prompt_parts.append("## 论文完整大纲")
    prompt_parts.append(full_outline_md)
    prompt_parts.append("")

    # 前序章节摘要
    if prev_chapters_summary:
        prompt_parts.append("## 已完成的章节摘要")
        prompt_parts.append(prev_chapters_summary)
        prompt_parts.append("")
        prompt_parts.append("请在写作时注意与前序章节保持逻辑连贯，避免重复内容。")
        prompt_parts.append("")

    # 当前章节
    prompt_parts.append("## 需要撰写的章节")
    prompt_parts.append(f"**{chapter_title}**")
    if chapter_description:
        prompt_parts.append(f"")
        prompt_parts.append(f"章节描述：{chapter_description}")
    prompt_parts.append(f"")
    prompt_parts.append(f"目标字数：约 {target_word_count:,} 字")

    # 用户补充数据
    if user_data:
        prompt_parts.append(f"")
        prompt_parts.append(f"**用户补充要求**：{user_data}")

    prompt_parts.append("")
    prompt_parts.append("请直接输出该章的 Markdown 正文内容。")

    return "\n".join(prompt_parts)


# ══════════════════════════════════════════════════════════════
# 前序章节摘要构建
# ══════════════════════════════════════════════════════════════

def build_prev_chapters_summary(chapters: list) -> str:
    """从前序章节列表构建摘要文本

    取每章的前 200 字作为摘要，让 LLM 了解上下文。

    Args:
        chapters: 已生成的 Chapter 对象列表

    Returns:
        str: 前序章节摘要文本
    """
    if not chapters:
        return ""

    summary_lines = []
    for i, ch in enumerate(chapters):
        if ch.content_markdown and ch.status in ("done", "edited"):
            # 取前 200 字作为摘要
            preview = ch.content_markdown[:200].replace("\n", " ")
            summary_lines.append(f"**{ch.node.title}**（{ch.word_count} 字）")
            summary_lines.append(f"> {preview}...")
            summary_lines.append("")

    return "\n".join(summary_lines)


# ══════════════════════════════════════════════════════════════
# 文献引用格式 Prompt（章节生成时附带）
# ══════════════════════════════════════════════════════════════

CITATION_GUIDELINES = """
## 文献引用规范

在正文中引用文献时，请遵守以下规范：
- 引用格式：使用方括号编号，如 "研究表明……[1]"
- 多个引用：使用逗号分隔，如 [1,3,5]
- 连续引用：使用连字符，如 [1-3]
- 引用的文献应有代表性、时效性（优先近5年）
- 每章至少引用3-5篇相关文献
"""
