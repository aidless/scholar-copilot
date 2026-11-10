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


def _evidence(method: str, **kw) -> dict:
    ev = {"method": method, "source": "crossref",
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


VERIFY_STATES = ("verified", "suspicious", "fake")
_TITLE_MATCH = 0.85   # ≥0.85 → verified
_TITLE_SUSPECT = 0.55  # 0.55~0.85 → suspicious；<0.55 → fake


async def verify_citation(title: str, doi: str | None = None,
                          year: int | None = None) -> dict:
    """单条引用核查。返回 {"state": ..., "similarity": ..., "evidence": {...}}。

    判定顺序：有 DOI 先查 DOI（命中即 verified，可附年份不一致降级 suspicious）；
    无 DOI 或 DOI 查无 → 标题模糊匹配。
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

    # 2) 标题模糊匹配
    try:
        candidates = await _crossref_title(title)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"核查源不可用：crossref {exc}") from None

    best, best_sim = None, 0.0
    for cand in candidates:
        if not cand.get("title"):
            continue
        sim = _similarity(title, cand["title"])
        if sim > best_sim:
            best, best_sim = cand, sim

    if best is None or best_sim < _TITLE_SUSPECT:
        result = {"state": "fake", "similarity": round(best_sim, 3),
                  "evidence": _evidence("title-match", matched_title=None,
                                        candidates_checked=len(candidates))}
    elif best_sim < _TITLE_MATCH:
        result = {"state": "suspicious", "similarity": round(best_sim, 3),
                  "evidence": _evidence("title-match", matched_title=best["title"],
                                        matched_year=best.get("year"), venue=best.get("venue"),
                                        matched_doi=best.get("doi"))}
    else:
        year_ok = (year is None or best.get("year") == year)
        state = "verified" if year_ok else "suspicious"
        result = {"state": state, "similarity": round(best_sim, 3),
                  "evidence": _evidence("title-match", matched_title=best["title"],
                                        matched_year=best.get("year"), venue=best.get("venue"),
                                        matched_doi=best.get("doi"),
                                        year_mismatch=None if year_ok else year)}
    _cache_put(key, result)
    return result
