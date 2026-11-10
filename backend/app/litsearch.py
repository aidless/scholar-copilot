"""文献检索服务：三源降级（OpenAlex → Crossref → Semantic Scholar），全部实时查库。

卖点（对照原产品「百分百真实」口头承诺）：每条结果带 DOI/链接真实存在，
是实时查库所得，不是 LLM 编造。进程内 TTL 缓存吸收限流。

凭据（可选，SC_* 环境变量）：OpenAlex 的 mailto 可进礼貌池提升稳定性；
S2_API_KEY 提升 Semantic Scholar 限额。无凭据也能跑。
"""
import logging
import re
import time

import httpx

from .config import settings

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


def _norm_semantic(item: dict) -> dict | None:
    title = item.get("title")
    if not title:
        return None
    return {
        "title": title,
        "authors": [a.get("name", "") for a in (item.get("authors") or []) if a.get("name")][:8],
        "year": item.get("year"),
        "doi": ((item.get("externalIds") or {}).get("DOI") or ""),
        "url": (f"https://doi.org/{item['externalIds']['DOI']}"
                if (item.get("externalIds") or {}).get("DOI") else None),
        "venue": (item.get("venue") or None),
        "cited_by": item.get("citationCount", 0),
        "source": "semantic_scholar",
    }


def _norm_pubmed(item: dict) -> dict | None:
    """PubMed esummary 结果归一化。doi 需从 articleids 里挑（不是每个条目都有）。"""
    title = (item.get("title") or "").strip()
    if not title:
        return None
    doi = ""
    for aid in item.get("articleids") or []:
        if aid.get("idtype") == "doi" and aid.get("value"):
            doi = aid["value"]
            break
    year = None
    pubdate = item.get("pubdate") or ""
    if pubdate[:4].isdigit():
        year = int(pubdate[:4])
    authors = [a.get("name", "") for a in (item.get("authors") or []) if a.get("name")]
    return {
        "title": title.rstrip("."),
        "authors": authors[:8],
        "year": year,
        "doi": doi,
        "url": (f"https://doi.org/{doi}" if doi
                else f"https://pubmed.ncbi.nlm.nih.gov/{item.get('uid')}/"),
        "venue": item.get("fulljournalname") or item.get("source"),
        "cited_by": 0,  # esummary 不返回被引数（要 elink 再查一轮，成本不划算）
        "source": "pubmed",
    }


async def _openalex(q: str, limit: int) -> list[dict]:
    params = {
        "search": q,
        "per-page": min(limit, 25),
        "select": "doi,title,display_name,publication_year,cited_by_count,authorships,primary_location",
        "sort": "relevance_score:desc",
    }
    if settings.openalex_mailto:
        params["mailto"] = settings.openalex_mailto
    if settings.openalex_api_key:
        params["api_key"] = settings.openalex_api_key
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


async def _semantic(q: str, limit: int) -> list[dict]:
    headers = {}
    if settings.semantic_scholar_api_key:
        headers["x-api-key"] = settings.semantic_scholar_api_key
    params = {"query": q, "limit": min(limit, 20),
              "fields": "title,authors,year,venue,citationCount,externalIds"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get("https://api.semanticscholar.org/graph/v1/paper/search",
                             params=params, headers=headers)
        r.raise_for_status()
        return [n for x in r.json().get("data", []) if (n := _norm_semantic(x))]


async def _pubmed(q: str, limit: int) -> list[dict]:
    """PubMed 两步检索：esearch 拿 PMID 列表，esummary 拿元数据。

    为什么两步：esearch 只回 id，esummary 才有标题/作者/DOI。两步各一次请求，
    比 efetch 的 XML 解析省事且字段够用。
    """
    common = {"db": "pubmed", "retmode": "json"}
    if settings.pubmed_api_key:
        common["api_key"] = settings.pubmed_api_key
    if settings.pubmed_email:
        common["email"] = settings.pubmed_email

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r1 = await client.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                              params={**common, "term": q, "retmax": min(limit, 20)})
        r1.raise_for_status()
        ids = (r1.json().get("esearchresult") or {}).get("idlist") or []
        if not ids:
            return []
        r2 = await client.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                              params={**common, "id": ",".join(ids)})
        r2.raise_for_status()
        result = r2.json().get("result") or {}
        items = [result[i] for i in ids if i in result]
        return [n for x in items if (n := _norm_pubmed(x))]


def _dedupe(results: list[dict]) -> list[dict]:
    """按 DOI（无 DOI 用规范化标题）去重，保留先到的（源优先级更高）。"""
    seen: set[str] = set()
    out: list[dict] = []
    for r in results:
        key = (r.get("doi") or "").lower().strip() or re.sub(r"\W+", "", (r.get("title") or "").lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


async def search_literature(q: str, limit: int = 8) -> dict:
    """四源依次降级：OpenAlex → Crossref → Semantic Scholar → PubMed。

    每个源失败只记日志继续下一个；全部失败才抛 RuntimeError（路由层转 502）。
    任一本源返回非空即停——多源是为了「这个源挂了还有别的」，不是为了混排。

    Returns:
        {"results": [...], "source": "<源名>|cache", "cached": bool}
    """
    key = f"{q.strip().lower()}|{limit}"
    cached = _cache_get(key)
    if cached is not None:
        return {"results": cached, "source": "cache", "cached": True}

    errors: list[str] = []
    sources = [("openalex", _openalex), ("crossref", _crossref), ("semantic_scholar", _semantic)]
    if settings.pubmed_enabled:
        sources.append(("pubmed", _pubmed))
    for name, fn in sources:
        try:
            results = await fn(q, limit)
            if results:
                results = _dedupe(results)[:limit]
                _cache_put(key, results)
                return {"results": results, "source": name, "cached": False}
            errors.append(f"{name}: 0 results")
        except Exception as exc:  # noqa: BLE001——单源失败降级下一源
            log.warning("literature source %s failed: %s", name, exc)
            errors.append(f"{name}: {exc}")

    raise RuntimeError("所有文献源不可用：" + "; ".join(errors))
