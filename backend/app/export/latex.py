"""LaTeX 导出：ctexart 单文件（中文友好），可直接 xelatex 编译。

取舍：不做「伪模板」堆砌，只输出结构正确、可编译的最小骨架；
水印/披露表在 DOCX 侧已强制，LaTeX 侧同样插入 AI 参与度披露表与免责声明页。
"""
from typing import Iterable

_TEX_SPECIALS = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}

_AI_LEVEL_ZH = {"A": "AI 生成未修改", "B": "AI 初稿已修改", "C": "人工撰写"}


def escape_latex(text: str) -> str:
    return "".join(_TEX_SPECIALS.get(ch, ch) for ch in text)


def _md_to_tex(md: str) -> str:
    """极简 Markdown→TeX：### 小标题、| 表格 → tabular、其余按段落。"""
    out: list[str] = []
    for raw in (md or "").splitlines():
        line = raw.rstrip()
        s = line.strip()
        if not s:
            out.append("")
            continue
        if s.startswith("###"):
            out.append(f"\\subsubsection*{{{escape_latex(s.lstrip('#').strip())}}}")
        elif s.startswith("##"):
            out.append(f"\\subsection*{{{escape_latex(s.lstrip('#').strip())}}}")
        elif s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            out.append(" & ".join(escape_latex(c) for c in cells) + r" \\ \hline")
        else:
            out.append(escape_latex(s))
    # 连续 | 行包成 tabular
    return "\n".join(out)


def _wrap_tables(tex: str) -> str:
    lines = tex.splitlines()
    res: list[str] = []
    in_table = False
    for ln in lines:
        is_row = ln.endswith(r"\\ \hline")
        if is_row and not in_table:
            res.append(r"\begin{tabular}{|l|l|l|l|}")
            res.append(r"\hline")
            in_table = True
        if in_table and not is_row:
            res.append(r"\end{tabular}")
            in_table = False
        res.append(ln)
    if in_table:
        res.append(r"\end{tabular}")
    return "\n".join(res)


def build_thesis_tex(title: str, education: str, chapters: Iterable[dict], language: str = "zh") -> bytes:
    parts: list[str] = [
        r"\documentclass[12pt,a4paper]{ctexart}",
        r"\usepackage[margin=2.5cm]{geometry}",
        r"\usepackage{longtable}",
        r"\usepackage{array}",
        r"\begin{document}",
        r"\begin{titlepage}",
        r"\centering",
        r"\vspace*{4cm}",
        r"{\Huge\bfseries " + escape_latex(title) + r"}\par",
        r"\vspace{1.5cm}",
        r"{\large 学历层次：" + escape_latex(education) + r"}\par",
        r"\vfill",
        r"{\small 本文档由 Scholar Copilot 辅助生成，AI 参与度见下表。}",
        r"\end{titlepage}",
        r"\section*{AI 参与度披露}",
        r"\begin{longtable}{|p{4cm}|p{2cm}|p{4cm}|}",
        r"\hline 章节 & 字数 & AI 参与度 \\ \hline",
    ]
    chap_list = list(chapters)
    for c in chap_list:
        parts.append(
            f"{escape_latex(c.get('title', ''))} & {c.get('word_count', 0)} & "
            f"{escape_latex(_AI_LEVEL_ZH.get(c.get('ai_level', 'C'), '人工撰写'))} \\\\ \\hline"
        )
    parts += [
        r"\end{longtable}",
        r"\clearpage",
    ]
    for c in chap_list:
        parts.append(r"\section*{" + escape_latex(c.get("title", "")) + "}")
        parts.append(_wrap_tables(_md_to_tex(c.get("content_md", ""))))
        parts.append("")
    parts += [
        r"\clearpage",
        r"\section*{免责声明}",
        r"本文档为学术写作辅助产出，作者须对最终内容、引用真实性与学术规范负全部责任；",
        r"提交前请按所在机构要求披露 AI 使用情况。",
        r"\end{document}",
    ]
    return "\n".join(parts).encode("utf-8")
