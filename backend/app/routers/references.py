"""文献端点：实时检索（OpenAlex/Crossref）+ 选定文献挂到订单。

与原产品差异：推荐结果是真实查库所得并带 DOI 链接，可复核；
v0.4 再加单条引用核查（verify_state 状态机已在表里预留）。
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..citecheck import verify_citation as check_citation
from ..db import get_db
from ..export.citation import STYLES as CITATION_STYLES
from ..export.charts import render_chart
from ..export.citation import render as render_citations
from ..litsearch import search_literature
from ..models import LocalReference, ReferenceItem, WritingOrder
from ..offline import parse_bibtex, parse_cnki, search_local, verify_local
from ..config import settings
from ..ratelimit import rate_limit_search
from ..security import parse_token
from ..tenancy import CurrentUser, current_user, ownership_filter

router = APIRouter(prefix="/references", tags=["references"])


@router.get("/search", dependencies=[Depends(rate_limit_search)])
async def search(q: str = Query(min_length=2, max_length=200), limit: int = 8,
                 db: AsyncSession = Depends(get_db),
                 authorization: str = Header(default="")):
    """外网检索；`SC_OFFLINE_MODE=true` 时改为查本地文献库（不出网）。"""
    if not settings.offline_mode:
        try:
            return await search_literature(q, limit)
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from None

    # 离线：必须能认出是谁（本地库按属主隔离）；未登录就明确告知而不是返回空
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "离线模式下列表检索需要登录（本地库按用户隔离）")
    payload = parse_token(authorization.removeprefix("Bearer "))
    if payload is None:
        raise HTTPException(401, "登录已过期")
    owner = payload["sub"]
    rows = (await db.execute(
        select(LocalReference).where(LocalReference.owner_id == owner)
        .limit(2000)
    )).scalars().all()
    items = [{"title": r.title, "authors": r.authors_json or [], "year": r.year,
              "venue": r.venue, "doi": r.doi, "url": None, "cited_by": 0,
              "kind": r.kind, "source": "local"} for r in rows]
    return {"source": "local", "items": search_local(q, items, limit)}


class RefIn(BaseModel):
    title: str = Field(min_length=2, max_length=500)
    authors: list[str] = []
    year: int | None = None
    doi: str | None = None
    url: str | None = None
    cited_by: int = 0
    kind: str = "journal"  # journal/book/web/custom


class RefsIn(BaseModel):
    items: list[RefIn] = Field(min_length=1, max_length=50)


@router.post("/orders/{order_id}")
async def attach_to_order(order_id: str, body: RefsIn,
                          db: AsyncSession = Depends(get_db),
                          user: CurrentUser = Depends(current_user)):
    order = (await db.execute(
        ownership_filter(select(WritingOrder), WritingOrder, user)
        .where(WritingOrder.id == order_id)
    )).scalar()
    if order is None:
        raise HTTPException(404, "订单不存在")
    added = []
    for item in body.items:
        row = ReferenceItem(
            tenant_id=user.tenant_id, owner_id=user.user_id, order_id=order_id,
            kind=item.kind, title=item.title,
            authors="; ".join(item.authors) if item.authors else None,
            year=item.year, doi=item.doi, url=item.url,
            cited_by=item.cited_by,
        )
        db.add(row)
        added.append(row)
    await db.commit()
    return {"attached": len(added), "ids": [r.id for r in added]}


@router.get("/orders/{order_id}")
async def list_order_refs(order_id: str, db: AsyncSession = Depends(get_db),
                          user: CurrentUser = Depends(current_user)):
    order = (await db.execute(
        ownership_filter(select(WritingOrder), WritingOrder, user)
        .where(WritingOrder.id == order_id)
    )).scalar()
    if order is None:
        raise HTTPException(404, "订单不存在")
    rows = (await db.execute(
        select(ReferenceItem).where(ReferenceItem.order_id == order_id)
        .order_by(ReferenceItem.created_at)
    )).scalars().all()
    return [{
        "id": r.id, "kind": r.kind, "title": r.title, "authors": r.authors,
        "year": r.year, "doi": r.doi, "url": r.url, "cited_by": r.cited_by,
        "verify_state": r.verify_state, "verify_evidence": r.verify_evidence,
    } for r in rows]


@router.get("/styles")
async def list_citation_styles():
    """可用引用格式（前端下拉用）。"""
    return {"styles": list(CITATION_STYLES.keys())}


@router.get("/orders/{order_id}/export")
async def export_order_refs(order_id: str,
                            style: str = Query(default="gb7714"),
                            db: AsyncSession = Depends(get_db),
                            user: CurrentUser = Depends(current_user)):
    """把订单挂载的文献导出成指定引用格式（gb7714/apa/ieee/bibtex/ris）。"""
    order = (await db.execute(
        ownership_filter(select(WritingOrder), WritingOrder, user)
        .where(WritingOrder.id == order_id)
    )).scalar()
    if order is None:
        raise HTTPException(404, "订单不存在")
    rows = (await db.execute(
        select(ReferenceItem).where(ReferenceItem.order_id == order_id)
        .order_by(ReferenceItem.created_at)
    )).scalars().all()
    if not rows:
        raise HTTPException(409, "订单还没有挂载文献，先 POST /references/orders/{id}")
    if style not in CITATION_STYLES:
        raise HTTPException(
            422, f"未知引用格式：{style}；可用值：{', '.join(CITATION_STYLES)}")
    items = [{
        "title": r.title, "authors": r.authors, "year": r.year,
        "doi": r.doi, "url": r.url, "kind": r.kind,
    } for r in rows]
    text, media, ext = render_citations(items, style)
    filename = quote(f"{order.title}-references.{ext}")
    return Response(
        content=text, media_type=media,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


# ── 引用真实性核查（v0.4）────────────────────────────────────

class VerifyItemIn(BaseModel):
    title: str = Field(min_length=2, max_length=500)
    doi: str | None = None
    year: int | None = None


class VerifyIn(BaseModel):
    items: list[VerifyItemIn] = Field(min_length=1, max_length=50)


@router.post("/verify")
async def verify_items(body: VerifyIn, db: AsyncSession = Depends(get_db),
                       authorization: str = Header(default="")):
    """临时引用核查（不落库）：逐条返回三态 + 证据。离线模式只查本地库。"""
    if settings.offline_mode:
        local: list[dict] = []
        if authorization.startswith("Bearer "):
            payload = parse_token(authorization.removeprefix("Bearer "))
            if payload is not None:
                rows = (await db.execute(
                    select(LocalReference).where(LocalReference.owner_id == payload["sub"])
                )).scalars().all()
                local = [{"title": r.title, "authors": r.authors_json or [],
                          "year": r.year, "venue": r.venue, "doi": r.doi} for r in rows]
        return {"results": [{"title": item.title,
                             **verify_local(item.title, local, item.year, item.doi)}
                            for item in body.items]}

    out = []
    for item in body.items:
        try:
            result = await check_citation(item.title, item.doi, item.year)
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from None
        out.append({"title": item.title, **result})
    return {"results": out}


# ── v1.12 #20：引用证据链可视化 ──────────────────────────────

class EvidenceIn(BaseModel):
    title: str = Field(min_length=2, max_length=500)
    doi: str | None = None
    year: int | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class EvidenceBatchIn(BaseModel):
    items: list[EvidenceIn] = Field(min_length=1, max_length=50)


def _evidence_chart(title: str, candidates: list[dict]) -> dict | None:
    """把候选列表变成条形图规格（可直接喂 /tools/chart 渲染）。"""
    if not candidates:
        return None
    labels = []
    values = []
    for c in candidates:
        ctitle = (c.get("title") or "（无标题）")
        # 标签太长图里看不清，截断到 28 字并标注年份
        short = ctitle if len(ctitle) <= 28 else ctitle[:27] + "…"
        year = c.get("year")
        labels.append(f"{short}（{year}）" if year else short)
        values.append(float(c.get("similarity") or 0.0))
    return {
        "type": "bar",
        "title": f"引用相似度候选：{title}",
        "labels": labels,
        "series": [{"name": "相似度", "values": values}],
        "xlabel": "候选文献",
        "ylabel": "相似度",
    }


@router.post("/verify/evidence")
async def verify_evidence(body: EvidenceBatchIn):
    """逐条核查并返回证据链（Top-N 候选 + 条形图规格）。

    与 /references/verify 的区别：这里把「像哪几篇、各自多像」摊开，
    让用户能自己判断，而不是只拿到三态标签。
    """
    out = []
    for item in body.items:
        try:
            result = await check_citation(item.title, item.doi, item.year,
                                          top_k=item.top_k)
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from None
        candidates = result.get("candidates") or []
        out.append({
            "title": item.title,
            "state": result["state"],
            "similarity": result["similarity"],
            "evidence": result["evidence"],
            "candidates": candidates,
            "chart": _evidence_chart(item.title, candidates),
        })
    return {"results": out}


@router.post("/verify/evidence/chart")
async def verify_evidence_chart(body: EvidenceIn):
    """直接渲染证据链条形图 PNG（前端 <img src> 可用）。"""
    try:
        result = await check_citation(body.title, body.doi, body.year,
                                      top_k=body.top_k)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from None
    spec = _evidence_chart(body.title, result.get("candidates") or [])
    if spec is None:
        raise HTTPException(404, "没有候选文献可画图")
    try:
        png = render_chart(spec)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return Response(content=png, media_type="image/png")


@router.get("/orders/{order_id}/evidence")
async def order_evidence(order_id: str, db: AsyncSession = Depends(get_db),
                          user: CurrentUser = Depends(current_user)):
    """订单文献的证据链快照（读已存的 verify_evidence + 候选列表）。"""
    order = (await db.execute(
        ownership_filter(select(ReferenceItem), ReferenceItem, user)
        .where(ReferenceItem.order_id == order_id)
    )).scalars().all()
    owner = (await db.execute(
        ownership_filter(select(WritingOrder), WritingOrder, user)
        .where(WritingOrder.id == order_id)
    )).scalar()
    if owner is None:
        raise HTTPException(404, "订单不存在")
    out = []
    for r in order:
        evidence = r.verify_evidence or {}
        candidates = evidence.get("candidates") or []
        out.append({
            "id": r.id, "title": r.title, "state": r.verify_state,
            "evidence": evidence, "candidates": candidates,
            "chart": _evidence_chart(r.title, candidates),
        })
    return {"order_id": order_id, "results": out}


@router.post("/orders/{order_id}/verify")
async def verify_order_refs(order_id: str, db: AsyncSession = Depends(get_db),
                            user: CurrentUser = Depends(current_user)):
    """批量核查订单文献：更新每行 verify_state / verify_evidence，返回汇总。"""
    order = (await db.execute(
        ownership_filter(select(WritingOrder), WritingOrder, user)
        .where(WritingOrder.id == order_id)
    )).scalar()
    if order is None:
        raise HTTPException(404, "订单不存在")
    rows = (await db.execute(
        select(ReferenceItem).where(ReferenceItem.order_id == order_id)
    )).scalars().all()
    if not rows:
        raise HTTPException(409, "订单还没有挂载文献，先 POST /references/orders/{id}")

    summary = {"verified": 0, "suspicious": 0, "fake": 0, "unverified": 0}
    for row in rows:
        try:
            result = await check_citation(row.title, row.doi, row.year)
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from None
        row.verify_state = result["state"]
        evidence = dict(result["evidence"])
        evidence["candidates"] = result.get("candidates") or []
        row.verify_evidence = evidence
        summary[result["state"]] += 1
    await db.commit()

    return {
        "checked": len(rows),
        "summary": summary,
        "all_real": summary["fake"] == 0 and summary["suspicious"] == 0,
        "results": [{"id": r.id, "title": r.title, "state": r.verify_state,
                     "evidence": r.verify_evidence} for r in rows],
    }


# ── v1.12 #21：本地文献库（离线模式的检索与核查数据源） ──────

class LibraryImportIn(BaseModel):
    format: str = Field(description="bibtex | cnki")
    content: str


class LibrarySearchIn(BaseModel):
    q: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=8, ge=1, le=50)


_LIBRARY_PARSERS = {"bibtex": parse_bibtex, "cnki": parse_cnki}


@router.post("/library/import", status_code=201)
async def import_library(body: LibraryImportIn, db: AsyncSession = Depends(get_db),
                         user: CurrentUser = Depends(current_user)):
    """导入 BibTeX 或 CNKI 导出文本。按 (标题, 年份) 去重，重复条目计 skipped。"""
    parser = _LIBRARY_PARSERS.get(body.format.strip().lower())
    if parser is None:
        raise HTTPException(422, f"不支持的格式：{body.format}（支持 bibtex / cnki）")
    items = parser(body.content or "")
    if not items:
        raise HTTPException(422, "未解析出任何条目，请检查文件格式")

    existing = (await db.execute(
        select(LocalReference.title, LocalReference.year)
        .where(LocalReference.owner_id == user.user_id)
    )).all()
    seen = {(t, y) for t, y in existing}

    imported = skipped = 0
    for item in items:
        key = (item.title, item.year)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        db.add(LocalReference(tenant_id=user.tenant_id, owner_id=user.user_id,
                              title=item.title, authors_json=item.authors,
                              year=item.year, venue=item.venue, doi=item.doi,
                              abstract=item.abstract, kind=item.kind))
        imported += 1
    await db.commit()
    return {"format": body.format.lower(), "imported": imported, "skipped": skipped}


@router.get("/library")
async def list_library(limit: int = 200, db: AsyncSession = Depends(get_db),
                       user: CurrentUser = Depends(current_user)):
    rows = (await db.execute(
        select(LocalReference).where(LocalReference.owner_id == user.user_id)
        .order_by(LocalReference.created_at.desc()).limit(min(max(limit, 1), 2000))
    )).scalars().all()
    return {"total": len(rows), "items": [
        {"id": r.id, "title": r.title, "authors": r.authors_json or [],
         "year": r.year, "venue": r.venue, "doi": r.doi, "kind": r.kind}
        for r in rows]}


@router.post("/library/search")
async def search_library(body: LibrarySearchIn, db: AsyncSession = Depends(get_db),
                         user: CurrentUser = Depends(current_user)):
    """本地检索（在线/离线都可用，不必开离线模式）。"""
    rows = (await db.execute(
        select(LocalReference).where(LocalReference.owner_id == user.user_id).limit(2000)
    )).scalars().all()
    items = [{"id": r.id, "title": r.title, "authors": r.authors_json or [],
              "year": r.year, "venue": r.venue, "doi": r.doi, "kind": r.kind}
             for r in rows]
    return {"items": search_local(body.q, items, body.limit), "library_size": len(items)}
