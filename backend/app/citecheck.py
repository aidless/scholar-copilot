"""引用真实性核查：DOI 查库 + 标题模糊匹配，全部结论带证据。

对照原产品「百分百真实」口头承诺：这里是可复核的核查——每条引用给出
verified / suspicious / fake 三态 + 命中证据（命中标题/年份/相似度/来源），
不闭环的绝不装 verified。源用 Crossref（免费无密钥，限流宽松于 OpenAlex）。
"""
import difflib
import logging
import re
import time
from datetime import datetime, timezone

import httpx

from .config import settings

log = logging.getLogger(__name__)

_TIMEOUT = 15.0
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 3600.0


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (s or "").lower())


def _cache_get(key: str) -> dict | None:
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL:
        return hit[1]
    return None


def _cache_put(key: str, value: dict) -> None:
    _CACHE[key] = (time.monotonic(), value)


def _evidence(method: str, source: str = "crossref", **kw) -> dict:
    ev = {"method": method, "source": source,
          "checked_at": datetime.now(timezone.utc).isoformat()}
    ev.update(kw)
    return ev


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


async def _crossref_doi(doi: str) -> dict | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(f"https://api.crossref.org/works/{doi}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        msg = r.json()["message"]
        issued = (msg.get("issued") or {}).get("date-parts") or [[None]]
        return {
            "title": (msg.get("title") or [None])[0],
            "year": issued[0][0] if issued and issued[0] else None,
            "venue": (msg.get("container-title") or [None])[0],
            "doi": msg.get("DOI"),
        }


async def _crossref_title(title: str) -> list[dict]:
    params = {
        "query.bibliographic": title,
        "rows": 3,
        "select": "DOI,title,issued,container-title",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get("https://api.crossref.org/works", params=params)
        r.raise_for_status()
        out = []
        for msg in r.json()["message"]["items"]:
            issued = (msg.get("issued") or {}).get("date-parts") or [[None]]
            out.append({
                "title": (msg.get("title") or [None])[0],
                "year": issued[0][0] if issued and issued[0] else None,
                "venue": (msg.get("container-title") or [None])[0],
                "doi": msg.get("DOI"),
            })
        return out


async def _s2_title(title: str) -> list[dict]:
    """Semantic Scholar 标题检索（Crossref 无果时的第二源）。"""
    headers = {}
    if settings.semantic_scholar_api_key:
        headers["x-api-key"] = settings.semantic_scholar_api_key
    params = {"query": title, "limit": 3, "fields": "title,year,venue,externalIds"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get("https://api.semanticscholar.org/graph/v1/paper/search",
                             params=params, headers=headers)
        r.raise_for_status()
        out = []
        for item in r.json().get("data", []):
            out.append({"title": item.get("title"), "year": item.get("year"),
                        "venue": item.get("venue"),
                        "doi": (item.get("externalIds") or {}).get("DOI"),
                        "source": "semantic_scholar"})
        return out


async def _pubmed_title(title: str) -> list[dict]:
    """PubMed 标题检索（第三源）。医学/临床文献常只在 PubMed 有 DOI。

    走和 litsearch 相同的两步：esearch 拿 PMID → esummary 拿元数据。
    """
    common = {"db": "pubmed", "retmode": "json"}
    if settings.pubmed_api_key:
        common["api_key"] = settings.pubmed_api_key
    if settings.pubmed_email:
        common["email"] = settings.pubmed_email
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r1 = await client.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                              params={**common, "term": title, "retmax": 3})
        r1.raise_for_status()
        ids = (r1.json().get("esearchresult") or {}).get("idlist") or []
        if not ids:
            return []
        r2 = await client.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                              params={**common, "id": ",".join(ids)})
        r2.raise_for_status()
        result = r2.json().get("result") or {}
    out = []
    for uid in ids:
        item = result.get(uid)
        if not item or not item.get("title"):
            continue
        doi = ""
        for aid in item.get("articleids") or []:
            if aid.get("idtype") == "doi" and aid.get("value"):
                doi = aid["value"]
                break
        pubdate = item.get("pubdate") or ""
        out.append({
            "title": item["title"].rstrip("."),
            "year": int(pubdate[:4]) if pubdate[:4].isdigit() else None,
            "venue": item.get("fulljournalname") or item.get("source"),
            "doi": doi,
            "source": "pubmed",
        })
    return out


VERIFY_STATES = ("verified", "suspicious", "fake")
_TITLE_MATCH = 0.85   # ≥0.85 → verified
_TITLE_SUSPECT = 0.55  # 0.55~0.85 → suspicious；<0.55 → fake


async def verify_citation(title: str, doi: str | None = None,
                          year: int | None = None) -> dict:
    """单条引用核查。返回 {"state": ..., "similarity": ..., "evidence": {...}}。

    判定顺序：有 DOI 先查 DOI（命中即 verified，可附年份不一致降级 suspicious）；
    无 DOI 或 DOI 查无 → 标题模糊匹配，Crossref → Semantic Scholar → PubMed 逐源补查，
    任一本源达到 verified 阈值即停（多源是为了「这个查不到还有别的」，不是混排打分）。
    """
    key = f"{_norm(title)}|{doi or ''}|{year or ''}"
    cached = _cache_get(key)
    if cached is not None:
        return dict(cached)

    # 1) DOI 直查
    if doi:
        try:
            meta = await _crossref_doi(doi.strip().removeprefix("https://doi.org/"))
        except Exception as exc:  # noqa: BLE001——单条失败不炸批量
            meta = None
            log.warning("doi lookup failed for %s: %s", doi, exc)
        if meta is not None:
            year_ok = (year is None or meta.get("year") == year)
            state = "verified" if year_ok else "suspicious"
            result = {
                "state": state,
                "similarity": 1.0,
                "evidence": _evidence("doi-lookup", matched_title=meta["title"],
                                      matched_year=meta.get("year"), venue=meta.get("venue"),
                                      year_mismatch=None if year_ok else year),
            }
            _cache_put(key, result)
            return result

    # 2) 标题模糊匹配：Crossref → 未达 verified 再补 Semantic Scholar（多源交叉）
    candidates: list[dict] = []
    errors: list[str] = []
    try:
        candidates += [{**c, "source": "crossref"} for c in await _crossref_title(title)]
    except Exception as exc:  # noqa: BLE001
        errors.append(f"crossref: {exc}")
        log.warning("citecheck crossref failed: %s", exc)

    def _best(cands: list[dict]) -> tuple[dict | None, float]:
        b, bs = None, 0.0
        for cand in cands:
            if not cand.get("title"):
                continue
            sim = _similarity(title, cand["title"])
            if sim > bs:
                b, bs = cand, sim
        return b, bs

    best, best_sim = _best(candidates)
    # 首源未达 verified → 依次补查后续源（S2 → PubMed），命中即停
    extra_sources = [("semantic_scholar", _s2_title)]
    if settings.pubmed_enabled:
        extra_sources.append(("pubmed", _pubmed_title))
    for src_name, fn in extra_sources:
        if best_sim >= _TITLE_MATCH:
            break
        try:
            candidates += await fn(title)
            best, best_sim = _best(candidates)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{src_name}: {exc}")
            log.warning("citecheck %s failed: %s", src_name, exc)

    if best is None:
        if errors:
            raise RuntimeError("核查源不可用：" + "; ".join(errors)) from None
        result = {"state": "fake", "similarity": 0.0,
                  "evidence": _evidence("title-match", matched_title=None,
                                        candidates_checked=len(candidates))}
    else:
        src = best.get("source", "crossref")
        if best_sim < _TITLE_SUSPECT:
            result = {"state": "fake", "similarity": round(best_sim, 3),
                      "evidence": _evidence("title-match", source=src, matched_title=None,
                                            candidates_checked=len(candidates))}
        elif best_sim < _TITLE_MATCH:
            result = {"state": "suspicious", "similarity": round(best_sim, 3),
                      "evidence": _evidence("title-match", source=src, matched_title=best["title"],
                                            matched_year=best.get("year"), venue=best.get("venue"),
                                            matched_doi=best.get("doi"))}
        else:
            year_ok = (year is None or best.get("year") == year)
            state = "verified" if year_ok else "suspicious"
            result = {"state": state, "similarity": round(best_sim, 3),
                      "evidence": _evidence("title-match", source=src, matched_title=best["title"],
                                            matched_year=best.get("year"), venue=best.get("venue"),
                                            matched_doi=best.get("doi"),
                                            year_mismatch=None if year_ok else year)}
    _cache_put(key, result)
    return result
