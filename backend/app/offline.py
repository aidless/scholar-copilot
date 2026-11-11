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

# 条目头：@type{key，body 由花括号配对确定（原文用 "\n}" 收尾，单行条目一律解析失败）
_BIB_HEAD = re.compile(r"@(\w+)\s*\{\s*([^,\n]*)")


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


def _iter_bib_entries(text: str):
    """按花括号配对切出每条 BibTeX 条目，返回 (entry_type, key, body)。

    不用正则整段匹配：字段值里的嵌套花括号（`title={Deep {GPU} Systems}`）会让
    惰性匹配提前收尾；手写扫描虽然朴素，但对「单行 / 多行 / 嵌套」一视同仁。
    """
    i, n = 0, len(text)
    while i < n:
        m = _BIB_HEAD.search(text, i)
        if not m:
            return
        entry_type, key = m.group(1), m.group(2).strip()
        j, depth = m.end(), 1
        while j < n and depth:
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield entry_type, key, text[m.end():j]
        i = j + 1


def _bib_fields(body: str) -> dict[str, str]:
    """按顶层逗号切字段，再按第一个 `=` 拆名值（值可带 {} 或 "")。"""
    parts, buf, depth = [], [], 0
    for ch in body:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))

    fields: dict[str, str] = {}
    for part in parts:
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        value = value.strip().rstrip(",").strip()
        if len(value) >= 2 and value[0] in "{\"" and value[-1] in "}\"":
            value = value[1:-1]
        fields[name.strip().lower()] = value
    return fields


def parse_bibtex(text: str) -> list[LocalRef]:
    """解析 BibTeX（单行/多行/嵌套花括号/引号值都支持）。"""
    out: list[LocalRef] = []
    if not text or not text.strip():
        return out
    for entry_type, key, body in _iter_bib_entries(text):
        fields = {k: _clean(v) for k, v in _bib_fields(body).items()}
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
                            raw=f"@{entry_type}{{{key}}}"))
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


def _query_tokens(q: str) -> list[str]:
    """查询分词：CJK 走二元组（中文没有空格），拉丁按空白/标点切词。"""
    text = _clean(q).lower()
    tokens = [w for w in re.split(r"[^0-9a-z\u4e00-\u9fff]+", text) if w]
    out: list[str] = []
    for tok in tokens:
        if all("\u4e00" <= ch <= "\u9fff" for ch in tok) and len(tok) > 2:
            out.extend(tok[i:i + 2] for i in range(len(tok) - 1))
        else:
            out.append(tok)
    return out


def search_local(q: str, items: list[dict], limit: int = 8) -> list[dict]:
    """本地检索：子串命中优先，其次按查询词覆盖率排序。

    只做子串匹配是不够的——用户输入「offline design」查「Offline First Design」
    会零命中，等于离线状态下没有检索。这里补一层词覆盖率（≥0.5 才收），
    既能命中词序不同的标题，也不会把不相关条目捞进来。
    """
    needle = (q or "").strip().lower()
    if not needle:
        return []
    tokens = _query_tokens(needle)

    hits: list[tuple[float, float, dict]] = []
    for item in items:
        title = (item.get("title") or "").lower()
        hay = " ".join([title, " ".join(item.get("authors") or []),
                        str(item.get("venue") or ""), str(item.get("doi") or "")]).lower()
        if needle in title:
            hits.append((2.0, 1.0, item))
            continue
        if needle in hay:
            hits.append((1.0, 1.0, item))
            continue
        if not tokens:
            continue
        covered = sum(1 for tok in tokens if tok in hay)
        coverage = covered / len(tokens)
        if coverage >= 0.5:
            # 标题命中比作者/来源命中更重要
            in_title = sum(1 for tok in tokens if tok in title) / len(tokens)
            hits.append((0.5 + in_title, coverage, item))

    hits.sort(key=lambda trip: (-trip[0], -trip[1]))
    return [item for _rank, _cov, item in hits[:limit]]


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
