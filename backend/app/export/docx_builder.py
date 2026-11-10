"""DOCX 构建器：封面 → AI 参与度披露表 → 章节正文（Markdown 轻渲染）→ 免责声明 + 水印。

合规护栏（本仓库对原产品的核心差异化）：导出文档必带
1. 每页水印「AI 辅助生成 · 仅供参考」
2. 《AI 参与度披露表》（章节 × A/B/C 层级，不可关）
3. 末页免责声明
"""
import io
import re
from datetime import date

from docx import Document
from docx.shared import Pt

from .watermark import AI_LEVEL_LABELS, add_disclaimer_page, add_watermark


def _add_disclosure_table(doc: Document, chapters: list[dict]) -> None:
    doc.add_heading("AI 参与度披露表", level=1)
    note = doc.add_paragraph()
    run = note.add_run(
        "层级说明：A = AI 生成，未经人工修改；B = AI 生成初稿，人工已修改；C = 人工撰写。"
        "本表由系统如实记录，提交前请自行复核并补足必要的人工撰写内容。"
    )
    run.font.size = Pt(9)

    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    header = table.rows[0].cells
    header[0].text = "章节"
    header[1].text = "字数"
    header[2].text = "AI 参与层级"
    for ch in chapters:
        row = table.add_row().cells
        row[0].text = ch["title"]
        row[1].text = str(ch.get("word_count", 0))
        level = ch.get("ai_level", "C")
        row[2].text = f"{level}（{AI_LEVEL_LABELS.get(level, '未知')}）"


def _render_markdown_block(doc: Document, lines: list[str]) -> None:
    """轻量 Markdown 渲染：### / #### 标题、| 表格、普通段落。"""
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if re.match(r"^#{3,6}\s+", stripped):
            level = len(stripped) - len(stripped.lstrip("#"))
            doc.add_heading(stripped[level:].strip(), level=min(level - 1, 4))
            i += 1
            continue

        if stripped.startswith("|"):
            # 收集连续表格行
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):  # 跳过分隔行
                    rows.append(cells)
                i += 1
            if rows:
                table = doc.add_table(rows=len(rows), cols=len(rows[0]))
                table.style = "Table Grid"
                for r, cells in enumerate(rows):
                    for c, text in enumerate(cells):
                        if c < len(table.rows[r].cells):
                            table.rows[r].cells[c].text = text
            continue

        if stripped:
            doc.add_paragraph(stripped)
        i += 1


def build_thesis_docx(title: str, education: str, chapters: list[dict],
                      language: str = "zh") -> bytes:
    """构建完整 DOCX 字节流。

    chapters: [{"idx", "node_id", "title", "content_md", "word_count", "ai_level"}]
    """
    doc = Document()

    # ── 封面 ──
    for _ in range(6):
        doc.add_paragraph()
    cover = doc.add_paragraph()
    cover.alignment = 1  # CENTER
    run = cover.add_run(title)
    run.bold = True
    run.font.size = Pt(22)
    meta = doc.add_paragraph()
    meta.alignment = 1
    meta_run = meta.add_run(f"{education}毕业论文 · {language} · {date.today().isoformat()}")
    meta_run.font.size = Pt(12)
    foot = doc.add_paragraph()
    foot.alignment = 1
    foot_run = foot.add_run("Scholar Copilot 生成 · 仅供学习研究参考")
    foot_run.font.size = Pt(9)
    doc.add_page_break()

    # ── AI 参与度披露表（合规招牌，不可关）──
    _add_disclosure_table(doc, chapters)
    doc.add_page_break()

    # ── 章节正文 ──
    for ch in chapters:
        doc.add_heading(ch["title"], level=1)
        content_md = ch.get("content_md") or ""
        _render_markdown_block(doc, content_md.split("\n"))

    # ── 伦理护栏 ──
    add_disclaimer_page(doc)
    add_watermark(doc)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
