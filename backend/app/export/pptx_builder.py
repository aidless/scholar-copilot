"""幻灯片生成：把「# 主标题 / ## 页标题 / - 要点」规格渲染成 PPTX。

不追求花哨模板：白底、大标题、要点列表——够用且可编辑（python-pptx 原生对象）。
"""
import io
import re

from pptx import Presentation
from pptx.util import Inches, Pt

_HEAD = re.compile(r"^##\s+(.+)$")
_BULLET = re.compile(r"^[-*]\s+(.+)$")


def parse_ppt_spec(md: str) -> dict:
    """解析 PPT 规格文本 → {title, subtitle, slides:[{title, bullets:[...]}]}"""
    title, subtitle = "演示文稿", None
    slides: list[dict] = []
    cur: dict | None = None

    for raw in (md or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# 主标题:"):
            title = line.split(":", 1)[1].strip()
        elif line.startswith("# 副标题:"):
            subtitle = line.split(":", 1)[1].strip()
        elif _HEAD.match(line):
            cur = {"title": _HEAD.match(line).group(1).strip(), "bullets": []}
            slides.append(cur)
        elif _BULLET.match(line):
            if cur is None:  # 没有页标题的要点 → 归入第一页
                cur = {"title": "概览", "bullets": []}
                slides.append(cur)
            cur["bullets"].append(_BULLET.match(line).group(1).strip())

    if not slides:
        raise ValueError("大纲解析失败：未找到任何页标题（##）")
    return {"title": title, "subtitle": subtitle, "slides": slides}


def build_pptx(spec: dict) -> bytes:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)  # 16:9

    # 封面
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = spec["title"]
    s.placeholders[1].text = spec.get("subtitle") or ""

    # 内容页
    for slide_spec in spec["slides"]:
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = slide_spec["title"]
        body = s.placeholders[1].text_frame
        body.clear()
        bullets = slide_spec["bullets"] or ["（本页要点待补充）"]
        for i, b in enumerate(bullets):
            p = body.paragraphs[0] if i == 0 else body.add_paragraph()
            p.text = b
            p.level = 0
            p.font.size = Pt(20)

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
