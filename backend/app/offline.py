"""离线模式与本地文献库（v1.12 #21）。

内网/无外网环境的痛点：/references/search 打 OpenAlex+Crossref+S2+PubMed 必超时，
整条「检索→引用→核查」链断掉。这里给出可用的降级路径：

1. 本地库：用户导入自己已有的 BibTeX / CNKI 导出文本，落库成可检索条目；
2. `SC_OFFLINE_MODE=true` 时，检索与核查都只查本地库，**不出网**；
3. 本地核查只做标题匹配，并把 source 标成 "local"——本地库没命中 ≠ 文献不存在，
   所以离线态下不判 "fake"，只判 verified/suspicious（避免误伤真实文献）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_BIB_ENTRY = re.compile(r"@(\w+)\s*\{\s*([^,]+),(.*?)\n\}", re.S)
_BIB_FIELD = re.compile(r"(\w+)\s*=\s*[{\"](.*?)[}\"]\s*,?\s*(?=\n\s*\w+\s*=|\Z)", re.S)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("{", "").replace("}", "")).strip()


@dataclass
class LocalRef:
    """本地库条目（解析结果，尚未落库）。"""

    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str | None = None
    abstract: str = ""
    kind: str = "journal"
    raw: str = ""

    def as_dict(self) -> dict:
        return {"title": self.title, "authors": self.authors, "year": self.year,
                "venue": self.venue, "doi": self.doi, "abstract": self.abstract,
                "kind": self.kind}

    # 让解析结果能像 dict 一样取字段：调用方（与测试）不必关心它是 dataclass
    def __getitem__(self, key: str):
        return self.as_dict()[key]

    def get(self, key: str, default=None):
        return self.as_dict().get(key, default)


def parse_bibtex(text: str) -> list[LocalRef]:
    """解析 BibTeX。只认最常用的花括号/引号字段，嵌套花括号做剥除处理。"""
    out: list[LocalRef] = []
    if not text or not text.strip():
        return out
    for entry_type, _key, body in _BIB_ENTRY.findall(text):
        fields = {k.lower(): _clean(v) for k, v in _BIB_FIELD.findall(body + "\n}")}
        title = fields.get("title", "")
        if not title:
            continue
        authors = [_clean(a) for a in re.split(r"\s+and\s+", fields.get("author", "")) if a.strip()]
        year = None
        m = re.search(r"\d{4}", fields.get("year", ""))
        if m:
            year = int(m.group(0))
        venue = fields.get("journal") or fields.get("booktitle") or fields.get("publisher") or ""
        kind = "book" if entry_type.lower() in ("book", "inbook") else "journal"
        out.append(LocalRef(title=title, authors=authors, year=year, venue=venue,
                            doi=fields.get("doi") or None,
                            abstract=fields.get("abstract", ""), kind=kind,
                            raw=f"@{entry_type}{{{ _key }}}"))
    return out


_CNKI_TITLE = re.compile(r"^\s*(?:题名|篇名|Title)\s*[:：]\s*(.+)$")
_CNKI_AUTHOR = re.compile(r"^\s*(?:作者|Author)\s*[:：]\s*(.+)$")
_CNKI_SOURCE = re.compile(r"^\s*(?:来源|期刊|Source|Journal)\s*[:：]\s*(.+)$")
_CNKI_YEAR = re.compile(r"^\s*(?:年|年份|Year)\s*[:：]\s*(\d{4})")
_CNKI_ABSTRACT = re.compile(r"^\s*(?:摘要|Abstract)\s*[:：]\s*(.+)$")


def parse_cnki(text: str) -> list[LocalRef]:
    """解析 CNKI 导出文本（题名/作者/来源/年/摘要 逐行，条目之间空行分隔）。"""
    out: list[LocalRef] = []
    if not text or not text.strip():
        return out
    current: dict = {}

    def flush() -> None:
        if current.get("title"):
            out.append(LocalRef(
                title=current["title"], authors=current.get("authors", []),
                year=current.get("year"), venue=current.get("venue", ""),
                abstract=current.get("abstract", ""), kind="journal",
                raw=current["title"],
            ))
        current.clear()

    for line in text.splitlines():
        if not line.strip():
            flush()
            continue
        if (m := _CNKI_TITLE.match(line)):
            flush()
            current["title"] = _clean(m.group(1))
        elif (m := _CNKI_AUTHOR.match(line)):
            current["authors"] = [_clean(x) for x in re.split(r"[;；,，]", m.group(1)) if x.strip()]
        elif (m := _CNKI_SOURCE.match(line)):
            current["venue"] = _clean(m.group(1))
        elif (m := _CNKI_YEAR.match(line)):
            current["year"] = int(m.group(1))
        elif (m := _CNKI_ABSTRACT.match(line)):
            current["abstract"] = _clean(m.group(1))
    flush()
    return out


def search_local(q: str, items: list[dict], limit: int = 8) -> list[dict]:
    """本地检索：标题/作者/来源/DOI 子串匹配，标题命中优先。"""
    needle = (q or "").strip().lower()
    if not needle:
        return []
    hits: list[tuple[int, dict]] = []
    for item in items:
        title = (item.get("title") or "").lower()
        hay = " ".join([title, " ".join(item.get("authors") or []),
                        str(item.get("venue") or ""), str(item.get("doi") or "")]).lower()
        if needle in title:
            hits.append((2, item))
        elif needle in hay:
            hits.append((1, item))
    hits.sort(key=lambda pair: -pair[0])
    return [item for _score, item in hits[:limit]]


def title_similarity(a: str, b: str) -> float:
    """标题相似度（0~1）：字符级 SequenceMatcher，对中英文都work。"""
    from difflib import SequenceMatcher

    a = _clean(a).lower()
    b = _clean(b).lower()
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


_TITLE_MATCH = 0.85
_TITLE_SUSPECT = 0.6


def verify_local(title: str, items: list[dict], year: int | None = None,
                 doi: str | None = None) -> dict:
    """离线核查：只用本地库。命中即 verified；相似但不够像 → suspicious。

    注意：离线态**不返回 fake**——本地库没有不代表文献是假的，判 fake 会误伤。
    """
    best = None
    best_score = 0.0
    for item in items:
        if doi and item.get("doi") and doi.lower() == str(item["doi"]).lower():
            best, best_score = item, 1.0
            break
        score = title_similarity(title, item.get("title") or "")
        if score > best_score:
            best, best_score = item, score
    if best is None or best_score < _TITLE_SUSPECT:
        return {"state": "unverified", "similarity": round(best_score, 4),
                "evidence": {"method": "local_title", "source": "local",
                             "candidates_checked": len(items),
                             "hint": "本地库未命中；离线模式不判定文献真伪"}}
    state = "verified" if best_score >= _TITLE_MATCH else "suspicious"
    evidence = {"method": "local_title", "source": "local",
                "matched_title": best.get("title"), "matched_year": best.get("year"),
                "venue": best.get("venue", ""), "matched_doi": best.get("doi"),
                "candidates_checked": len(items)}
    if year and best.get("year") and int(best["year"]) != int(year):
        state = "suspicious"
        evidence["year_mismatch"] = {"given": year, "local": best["year"]}
    return {"state": state, "similarity": round(best_score, 4), "evidence": evidence}
