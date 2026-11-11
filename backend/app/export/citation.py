"""引用格式导出：GB/T 7714-2015 / APA 7 / IEEE / BibTeX / RIS。

对照原产品：blsxueshu 只把文献挂在订单上、不做格式化，用户还得自己排。
开源版把五种主流格式做成纯函数（无 IO、无网络），既可导出成文，也可单独测试。

作者串约定：库里 authors 用 "；" 或 ";" 分隔；本模块统一按分隔符切成列表再按格式重排。
GB/T 7714 规则：≤3 人全列，>3 人列前 3 + ", 等"（英文用 ", et al"）。
"""
from __future__ import annotations

import re

_SEP = re.compile(r"[;；]")


def _authors(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [a.strip() for a in _SEP.split(raw) if a.strip()]


def _gb_authors(names: list[str]) -> str:
    if not names:
        return "佚名"
    if len(names) <= 3:
        return ", ".join(names)
    return ", ".join(names[:3]) + ", 等"


def _apa_authors(names: list[str]) -> str:
    """APA：Last, F. M. 形；中文名直接原样保留（APA 中文变体常见的做法）。"""
    if not names:
        return "Anon."
    all_cjk = all(any("\u4e00" <= ch <= "\u9fff" for ch in n) for n in names)
    out = []
    for n in names:
        # 已经是 "姓, 名" 形式则原样
        if "," in n:
            out.append(n)
            continue
        # 中文名（含 CJK）原样
        if any("\u4e00" <= ch <= "\u9fff" for ch in n):
            out.append(n)
            continue
        parts = n.split()
        if len(parts) == 1:
            out.append(parts[0])
        else:
            last = parts[-1]
            initials = " ".join(p[0] + "." for p in parts[:-1])
            out.append(f"{last}, {initials}")
    # 中文作者用逗号连接（APA 中文变体不用 &）
    if all_cjk:
        return ", ".join(out)
    if len(out) == 1:
        return out[0]
    if len(out) == 2:
        return f"{out[0]}, & {out[1]}"
    return ", ".join(out[:-1]) + f", & {out[-1]}"


def _ieee_authors(names: list[str]) -> str:
    """IEEE：F. M. Last 形；多位用逗号 + and 连接最后一位。"""
    if not names:
        return "Anonymous"
    out = []
    for n in names:
        if "," in n or any("\u4e00" <= ch <= "\u9fff" for ch in n):
            out.append(n)
            continue
        parts = n.split()
        if len(parts) == 1:
            out.append(parts[0])
        else:
            initials = " ".join(p[0] + "." for p in parts[:-1])
            out.append(f"{initials} {parts[-1]}")
    if len(out) == 1:
        return out[0]
    return ", ".join(out[:-1]) + " and " + out[-1]


_KIND_GB = {"journal": "[J]", "book": "[M]", "web": "[EB/OL]", "custom": "[Z]"}
_KIND_RIS = {"journal": "JOUR", "book": "BOOK", "web": "ELEC", "custom": "GEN"}
_KIND_BIB = {"journal": "article", "book": "book", "web": "misc", "custom": "misc"}


def _bibkey(item: dict, idx: int) -> str:
    title = (item.get("title") or "").strip()
    word = re.sub(r"[^A-Za-z0-9]", "", title.split(" ")[0]) if title else ""
    year = item.get("year") or "nd"
    return f"ref{idx}{('_' + word) if word else ''}{year}"


def to_gb7714(items: list[dict]) -> str:
    lines = []
    for i, it in enumerate(items, 1):
        authors = _gb_authors(_authors(it.get("authors")))
        title = (it.get("title") or "").strip().rstrip(".")
        kind = _KIND_GB.get(it.get("kind") or "journal", "[Z]")
        parts = [f"[{i}] {authors}. {title}{kind}"]
        if it.get("year"):
            parts.append(f", {it['year']}")
        if it.get("doi"):
            parts.append(f". DOI: {it['doi']}")
        elif it.get("url"):
            parts.append(f". {it['url']}")
        parts.append(".")
        lines.append("".join(parts))
    return "\n".join(lines)


def to_apa(items: list[dict]) -> str:
    lines = []
    for it in items:
        authors = _apa_authors(_authors(it.get("authors")))
        year = it.get("year") or "n.d."
        title = (it.get("title") or "").strip().rstrip(".")
        tail = ""
        if it.get("doi"):
            tail = f" https://doi.org/{it['doi']}"
        elif it.get("url"):
            tail = f" {it['url']}"
        lines.append(f"{authors} ({year}). {title}.{tail}".rstrip())
    return "\n".join(lines)


def to_ieee(items: list[dict]) -> str:
    lines = []
    for i, it in enumerate(items, 1):
        authors = _ieee_authors(_authors(it.get("authors")))
        title = (it.get("title") or "").strip().rstrip(".")
        year = it.get("year")
        seg = f'[{i}] {authors}, "{title}"'
        if year:
            seg += f", {year}"
        if it.get("doi"):
            seg += f", doi: {it['doi']}"
        elif it.get("url"):
            seg += f", [Online]. Available: {it['url']}"
        lines.append(seg + ".")
    return "\n".join(lines)


def to_bibtex(items: list[dict]) -> str:
    chunks = []
    for i, it in enumerate(items, 1):
        etype = _KIND_BIB.get(it.get("kind") or "journal", "misc")
        key = _bibkey(it, i)
        fields = [("title", (it.get("title") or "").strip())]
        names = _authors(it.get("authors"))
        if names:
            fields.append(("author", " and ".join(names)))
        if it.get("year"):
            fields.append(("year", str(it["year"])))
        if it.get("doi"):
            fields.append(("doi", it["doi"]))
        if it.get("url"):
            fields.append(("url", it["url"]))
        body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields if v)
        chunks.append(f"@{etype}{{{key},\n{body}\n}}")
    return "\n\n".join(chunks)


def to_ris(items: list[dict]) -> str:
    blocks = []
    for it in items:
        lines = [f"TY  - {_KIND_RIS.get(it.get('kind') or 'journal', 'GEN')}"]
        if it.get("title"):
            lines.append(f"TI  - {it['title'].strip()}")
        for n in _authors(it.get("authors")):
            lines.append(f"AU  - {n}")
        if it.get("year"):
            lines.append(f"PY  - {it['year']}")
        if it.get("doi"):
            lines.append(f"DO  - {it['doi']}")
        if it.get("url"):
            lines.append(f"UR  - {it['url']}")
        lines.append("ER  - ")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


STYLES = {
    "gb7714": (to_gb7714, "text/plain; charset=utf-8", "txt"),
    "apa": (to_apa, "text/plain; charset=utf-8", "txt"),
    "ieee": (to_ieee, "text/plain; charset=utf-8", "txt"),
    "bibtex": (to_bibtex, "application/x-bibtex; charset=utf-8", "bib"),
    "ris": (to_ris, "application/x-research-info-systems; charset=utf-8", "ris"),
}


def render(items: list[dict], style: str) -> tuple[str, str, str]:
    """返回 (正文, media_type, 扩展名)；未知 style 抛 KeyError。"""
    fn, media, ext = STYLES[style]
    return fn(items), media, ext
