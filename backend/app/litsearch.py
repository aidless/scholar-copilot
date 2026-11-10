"""文献检索服务：OpenAlex 主源 + Crossref 备源，免费无密钥。

卖点（对照原产品「百分百真实」口头承诺）：每条结果带 DOI/链接真实存在，
是实时查库所得，不是 LLM 编造。进程内 TTL 缓存吸收限流。
"""
import logging
import time

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = 15.0
_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL = 300.0


def _cache_get(key: str) -> list[dict] | None:
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL:
        return hit[1]
    return None


def _cache_put(key: str, value: list[dict]) -> None:
    _CACHE[key] = (time.monotonic(), value)


def _norm_openalex(item: dict) -> dict | None:
    title = item.get("title") or item.get("display_name")
    if not title:
        return None
    authors = [a.get("author", {}).get("display_name", "") for a in item.get("authorships", [])]
    venue = ((item.get("primary_location") or {}).get("source") or {}).get("display_name")
    return {
        "title": title,
        "authors": [a for a in authors if a][:8],
        "year": item.get("publication_year"),
        "doi": (item.get("doi") or "").removeprefix("https://doi.org/"),
        "url": item.get("doi") or (item.get("primary_location") or {}).get("landing_page_url"),
        "venue": venue,
        "cited_by": item.get("cited_by_count", 0),
        "source": "openalex",
    }


def _norm_crossref(item: dict) -> dict | None:
    title_list = item.get("title") or []
    if not title_list:
        return None
    issued = (item.get("issued") or {}).get("date-parts") or [[None]]
    year = issued[0][0] if issued and issued[0] else None
    return {
        "title": title_list[0],
        "authors": [
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in (item.get("author") or [])[:8]
        ],
        "year": year,
        "doi": item.get("DOI"),
        "url": item.get("URL") or (f"https://doi.org/{item['DOI']}" if item.get("DOI") else None),
        "venue": (item.get("container-title") or [None])[0],
        "cited_by": item.get("is-referenced-by-count", 0),
        "source": "crossref",
    }


async def _openalex(q: str, limit: int) -> list[dict]:
    params = {
        "search": q,
        "per-page": min(limit, 25),
        "select": "doi,title,display_name,publication_year,cited_by_count,authorships,primary_location",
        "sort": "relevance_score:desc",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get("https://api.openalex.org/works", params=params)
        r.raise_for_status()
        return [n for x in r.json().get("results", []) if (n := _norm_openalex(x))]


async def _crossref(q: str, limit: int) -> list[dict]:
    params = {
        "query": q,
        "rows": min(limit, 25),
        "select": "DOI,title,author,issued,container-title,is-referenced-by-count,URL",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get("https://api.crossref.org/works", params=params)
        r.raise_for_status()
        return [n for x in r.json()["message"]["items"] if (n := _norm_crossref(x))]


async def search_literature(q: str, limit: int = 8) -> dict:
    """OpenAlex 优先，失败降级 Crossref；两源都挂 → 502 语义由路由层转。

    Returns:
        {"results": [...], "source": "openalex|crossref", "cached": bool}
    """
    key = f"{q.strip().lower()}|{limit}"
    cached = _cache_get(key)
    if cached is not None:
        return {"results": cached, "source": "cache", "cached": True}

    errors: list[str] = []
    for name, fn in (("openalex", _openalex), ("crossref", _crossref)):
        try:
            results = await fn(q, limit)
            if results:
                _cache_put(key, results)
                return {"results": results, "source": name, "cached": False}
            errors.append(f"{name}: 0 results")
        except Exception as exc:  # noqa: BLE001——单源失败降级下一源
            log.warning("literature source %s failed: %s", name, exc)
            errors.append(f"{name}: {exc}")

    raise RuntimeError("所有文献源不可用：" + "; ".join(errors))
