"""核查面板：订单级论文体检（引用 / 数字一致性 / AI 参与度标记）。

原为 501 空壳，v1.8 落地：复用 app/audit.py 的纯函数规则引擎，
只读库内数据（含已核查的 verify_state），不发网络请求 → 幂等、离线可跑。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit as run_audit
from ..db import get_db
from ..models import OrderChapter, ReferenceItem, WritingOrder
from ..tenancy import CurrentUser, current_user, ownership_filter

router = APIRouter(prefix="/review", tags=["review"])


async def _load(db: AsyncSession, user: CurrentUser, order_id: str):
    order = (await db.execute(
        ownership_filter(select(WritingOrder), WritingOrder, user)
        .where(WritingOrder.id == order_id)
    )).scalar()
    if order is None:
        raise HTTPException(404, "订单不存在")
    chapters = (await db.execute(
        select(OrderChapter).where(OrderChapter.order_id == order_id)
        .order_by(OrderChapter.idx)
    )).scalars().all()
    refs = (await db.execute(
        select(ReferenceItem).where(ReferenceItem.order_id == order_id)
        .order_by(ReferenceItem.created_at)
    )).scalars().all()
    return order, chapters, refs


@router.post("/orders/{order_id}/audit")
async def audit(order_id: str,
                only: str = Query(default="", description="逗号分隔，只看某几条规则，如 ref_invalid,number_without_citation"),
                db: AsyncSession = Depends(get_db),
                user: CurrentUser = Depends(current_user)):
    order, chapters, refs = await _load(db, user, order_id)
    report = run_audit(
        chapters=[{"node_id": c.node_id, "title": c.title, "content_md": c.content_md,
                   "word_count": c.word_count, "ai_level": c.ai_level, "status": c.status}
                  for c in chapters],
        refs=[{"id": r.id, "title": r.title, "verify_state": r.verify_state,
               "verify_evidence": r.verify_evidence} for r in refs],
    )
    if only:
        wanted = {s.strip() for s in only.split(",") if s.strip()}
        report["issues"] = [i for i in report["issues"] if i["rule"] in wanted]
        report["summary"]["issues_total"] = len(report["issues"])
    report["order_id"] = order_id
    report["order_title"] = order.title
    return report


@router.get("/orders/{order_id}/audit/summary")
async def audit_summary(order_id: str, db: AsyncSession = Depends(get_db),
                        user: CurrentUser = Depends(current_user)):
    """轻量版：只看 verdict + summary，前端徽章/角标用。"""
    order, chapters, refs = await _load(db, user, order_id)
    report = run_audit(
        chapters=[{"node_id": c.node_id, "title": c.title, "content_md": c.content_md,
                   "word_count": c.word_count, "ai_level": c.ai_level, "status": c.status}
                  for c in chapters],
        refs=[{"id": r.id, "title": r.title, "verify_state": r.verify_state,
               "verify_evidence": r.verify_evidence} for r in refs],
    )
    return {"order_id": order_id, "verdict": report["verdict"], "summary": report["summary"]}
