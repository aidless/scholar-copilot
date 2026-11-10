"""水印、免责声明与 AI 参与度标记。

移植自 thesis_auto_generator/utils/watermark.py（P4 伦理护栏），
免责声明文案改为 Scholar Copilot 品牌语义。
"""
import logging

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

logger = logging.getLogger(__name__)

WATERMARK_TEXT = "AI 辅助生成 · 仅供参考"

DISCLAIMER_TITLE = "免责声明"
DISCLAIMER_BODY = (
    "本文档由 Scholar Copilot 使用 AI 大语言模型辅助生成，仅供学习、研究和参考之用。\n\n"
    "1. 本系统生成的内容基于用户输入的主题和大纲，由 AI 自动撰写，"
    "不代表任何学术机构的观点或立场。\n"
    "2. 生成内容可能存在事实性错误、逻辑不严谨或引用不当等问题，"
    "使用者应自行核实所有内容的准确性。\n"
    "3. 本系统承担的伦理责任以文档内附的《AI 参与度披露表》为准——"
    "各章节的 AI 参与层级如实标注，严禁将生成内容直接作为学位论文提交。\n"
    "4. 使用本系统即表示您已阅读并同意上述条款。"
)

# AI 参与度层级（语义与 thesis_auto_generator P4 对齐）
AI_LEVEL_LABELS = {
    "A": "AI 生成，未经人工修改",
    "B": "AI 生成初稿，人工已修改",
    "C": "人工撰写",
}


def create_watermark_xml(text: str = WATERMARK_TEXT) -> str:
    """生成 Word 水印的 VML XML 片段（插入页眉，每页可见）。"""
    return f'''<w:pict xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <v:shapetype id="_x0000_t136" coordsize="21600,21600" o:spt="136" adj="10800"
    path="m@7,l@8,m@5,21600l@6,21600e" filled="f"
    xmlns:v="urn:schemas-microsoft-com:vml"
    xmlns:o="urn:schemas-microsoft-com:office:office">
    <v:stroke joinstyle="miter"/>
  </v:shapetype>
  <v:shape id="watermarkShape" type="#_x0000_t136"
    style="position:absolute;margin-left:0;margin-top:0;width:450pt;height:200pt;rotation:315;z-index:-251658240;mso-position-horizontal:center;mso-position-vertical:center"
    fillcolor="#C0C0C0" stroked="f" opacity="0.25"
    xmlns:v="urn:schemas-microsoft-com:vml">
    <v:textpath style="font-family:&quot;宋体&quot;;font-size:1pt;font-weight:bold" string="{text}"/>
  </v:shape>
</w:pict>'''


def add_watermark(doc: Document) -> None:
    """向文档页眉注入水印；失败仅告警，不阻断导出主流程。"""
    try:
        section = doc.sections[0]
        header = section.header
        header.is_linked_to_previous = False
        paragraph = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run()
        run._element.append(parse_xml(create_watermark_xml(WATERMARK_TEXT)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("添加水印失败: %s", exc)


def add_disclaimer_page(doc: Document) -> None:
    """文档末尾追加免责声明页。"""
    try:
        doc.add_page_break()
        for _ in range(6):
            doc.add_paragraph()

        title_para = doc.add_paragraph()
        title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title_run = title_para.add_run(DISCLAIMER_TITLE)
        title_run.bold = True
        title_run.font.size = Pt(18)
        title_run.font.name = "黑体"
        title_run._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")

        doc.add_paragraph()

        body_para = doc.add_paragraph()
        body_para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        body_run = body_para.add_run(DISCLAIMER_BODY)
        body_run.font.size = Pt(11)
        body_run.font.name = "宋体"
        body_run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        body_para.paragraph_format.first_line_indent = Cm(0.74)
    except Exception as exc:  # noqa: BLE001
        logger.warning("添加免责声明页失败: %s", exc)
