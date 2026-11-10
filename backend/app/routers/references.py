"""文献端点：实时检索（OpenAlex/Crossref）+ 选定文献挂到订单。

与原产品差异：推荐结果是真实查库所得并带 DOI 链接，可复核；
v0.4 再加单条引用核查（verify_state 状态机已在表里预留）。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..citecheck import verify_citation as check_citation
from ..db import get_db
from ..litsearch import search_literature
from ..models import ReferenceItem, WritingOrder
from ..tenancy import CurrentUser, current_user, ownership_filter

router = APIRouter(prefix="/references", tags=["references"])


@router.get("/search")
async def search(q: str = Query(min_length=2, max_length=200), limit: int = 8,
                 db: AsyncSession = Depends(get_db)):
    del db  # 检索无库依赖，保留签名一致性
    try:
        out = await search_literature(q, limit)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from None
    return out


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


# ── 引用真实性核查（v0.4）────────────────────────────────────

class VerifyItemIn(BaseModel):
    title: str = Field(min_length=2, max_length=500)
    doi: str | None = None
    year: int | None = None


class VerifyIn(BaseModel):
    items: list[VerifyItemIn] = Field(min_length=1, max_length=50)


@router.post("/verify")
async def verify_items(body: VerifyIn):
    """临时引用核查（不落库）：逐条返回三态 + 证据。"""
    out = []
    for item in body.items:
        try:
            result = await check_citation(item.title, item.doi, item.year)
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from None
        out.append({"title": item.title, **result})
    return {"results": out}


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
        row.verify_evidence = result["evidence"]
        summary[result["state"]] += 1
    await db.commit()

    return {
        "checked": len(rows),
        "summary": summary,
        "all_real": summary["fake"] == 0 and summary["suspicious"] == 0,
        "results": [{"id": r.id, "title": r.title, "state": r.verify_state,
                     "evidence": r.verify_evidence} for r in rows],
    }
