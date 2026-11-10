"""格式排版：预设学校格式 profile 应用到导出 DOCX。

对照原产品 formatTemplate（education=1 返 20 条学校模板，隐藏接口）：
开源版给出 4 个通用 profile（本科/硕士/博士/英文），参数全部显式可查
（GET /formatting/profiles），自部署者可自行扩展——格式规则不再黑箱。
应用为全文重排版（字体/字号/行距/页边距/标题层级），不改动文字内容。
"""
import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

# 通用格式档案（值对齐国内高校学位论文常见规范；确认为「常见默认」而非某校官方）
FORMAT_PROFILES: dict[str, dict] = {
    "本科-通用": {
        "label": "本科通用：正文宋体小四 1.5 倍行距，章标题黑体三号居中",
        "body": {"east": "宋体", "latin": "Times New Roman", "size_pt": 12,
                 "line_spacing": 1.5, "first_line_indent_pt": 24},
        "heading1": {"east": "黑体", "size_pt": 16, "bold": True, "center": True},
        "heading2": {"east": "黑体", "size_pt": 14, "bold": True, "center": False},
        "heading3": {"east": "宋体", "size_pt": 12, "bold": True, "center": False},
        "page": {"top_cm": 2.54, "bottom_cm": 2.54, "left_cm": 3.0, "right_cm": 2.5},
    },
    "硕士-通用": {
        "label": "硕士通用：正文宋体小四 1.5 倍行距，章标题黑体三号居中，节标题黑体四号",
        "body": {"east": "宋体", "latin": "Times New Roman", "size_pt": 12,
                 "line_spacing": 1.5, "first_line_indent_pt": 24},
        "heading1": {"east": "黑体", "size_pt": 16, "bold": True, "center": True},
        "heading2": {"east": "黑体", "size_pt": 14, "bold": True, "center": False},
        "heading3": {"east": "黑体", "size_pt": 12, "bold": True, "center": False},
        "page": {"top_cm": 3.0, "bottom_cm": 2.5, "left_cm": 3.0, "right_cm": 2.5},
    },
    "博士-通用": {
        "label": "博士通用：正文宋体小四 1.5 倍行距，章标题黑体二号居中",
        "body": {"east": "宋体", "latin": "Times New Roman", "size_pt": 12,
                 "line_spacing": 1.5, "first_line_indent_pt": 24},
        "heading1": {"east": "黑体", "size_pt": 22, "bold": True, "center": True},
        "heading2": {"east": "黑体", "size_pt": 15, "bold": True, "center": False},
        "heading3": {"east": "黑体", "size_pt": 13, "bold": True, "center": False},
        "page": {"top_cm": 3.0, "bottom_cm": 2.5, "left_cm": 3.0, "right_cm": 2.5},
    },
    "英文-通用": {
        "label": "English generic: Times New Roman 12pt, 1.5 spacing, Arial headings",
        "body": {"east": "宋体", "latin": "Times New Roman", "size_pt": 12,
                 "line_spacing": 1.5, "first_line_indent_pt": 0},
        "heading1": {"east": "黑体", "latin": "Arial", "size_pt": 16, "bold": True, "center": False},
        "heading2": {"east": "黑体", "latin": "Arial", "size_pt": 14, "bold": True, "center": False},
        "heading3": {"east": "黑体", "latin": "Arial", "size_pt": 12, "bold": True, "center": False},
        "page": {"top_cm": 2.54, "bottom_cm": 2.54, "left_cm": 2.54, "right_cm": 2.54},
    },
}


def _set_style_font(style, spec: dict, default_latin: str = "Times New Roman") -> None:
    style.font.name = spec.get("latin", default_latin)
    style.font.size = Pt(spec["size_pt"])
    style.font.bold = spec.get("bold", False)
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), spec.get("east", "宋体"))


def apply_format_profile(docx_bytes: bytes, profile_key: str) -> bytes:
    """全文重排版：样式（Normal/Heading 1-3）+ 页边距；不改文字内容。"""
    profile = FORMAT_PROFILES.get(profile_key)
    if profile is None:
        raise KeyError(profile_key)

    doc = Document(io.BytesIO(docx_bytes))

    normal = doc.styles["Normal"]
    body = profile["body"]
    _set_style_font(normal, body)
    pf = normal.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = body["line_spacing"]
    if body.get("first_line_indent_pt"):
        pf.first_line_indent = Pt(body["first_line_indent_pt"])

    for level in (1, 2, 3):
        spec = profile[f"heading{level}"]
        style = doc.styles[f"Heading {level}"]
        _set_style_font(style, spec, default_latin=spec.get("latin", "Times New Roman"))
        if spec.get("center"):
            style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for section in doc.sections:
        section.top_margin = Cm(profile["page"]["top_cm"])
        section.bottom_margin = Cm(profile["page"]["bottom_cm"])
        section.left_margin = Cm(profile["page"]["left_cm"])
        section.right_margin = Cm(profile["page"]["right_cm"])

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
