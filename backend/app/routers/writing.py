"""写作订单端点：下单/大纲（配额服务端扣）/逐章/改稿/导出。

IDOR 修复点（对照逆向报告 P1-2）：全部资源访问先过 ownership_filter，
非本人/不存在一律统一 404——不区分「不存在」与「不属于你」。
价格纪律：客户端传的任何价格字段一律忽略，服务端按 billing 公式重算。
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..export.docx_builder import build_thesis_docx
from ..models import GenerationJob, OrderChapter, OrderOutline, QuotaLedger, WritingOrder
from ..tenancy import CurrentUser, current_user, ownership_filter
from ..tasks.local import launch, run_job
from ..writing.service import count_words, price_cents, quota_remaining

router = APIRouter(prefix="/writing", tags=["writing"])

_EDUCATIONS = ("本科", "硕士", "博士")


def _order_out(order: WritingOrder) -> dict:
    return {
        "id": order.id,
        "title": order.title,
        "education": order.education,
        "word_count": order.word_count,
        "language": order.language,
        "writing_type": order.writing_type,
        "status": order.status,
        "price_cents": order.price_cents,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


def _chapter_out(ch: OrderChapter) -> dict:
    return {
        "id": ch.id,
        "node_id": ch.node_id,
        "idx": ch.idx,
        "title": ch.title,
        "description": ch.description,
        "status": ch.status,
        "word_count": ch.word_count,
        "ai_level": ch.ai_level,
        "content_md": ch.content_md,
    }


def _job_out(job: GenerationJob) -> dict:
    return {
        "job_id": job.id,
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "result": job.result_json,
        "error": job.error,
        "tokens_in": job.tokens_in,
        "tokens_out": job.tokens_out,
        "model": job.model,
    }


async def _get_owned_order(db: AsyncSession, user: CurrentUser, order_id: str) -> WritingOrder:
    query = ownership_filter(select(WritingOrder), WritingOrder, user).where(
        WritingOrder.id == order_id)
    order = (await db.execute(query)).scalar()
    if order is None:  # 统一 404：不区分不存在与不属于你
        raise HTTPException(404, "订单不存在")
    return order


class OrderIn(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    education: str
    word_count: int = Field(gt=0, le=200_000)
    language: str = "zh"
    writing_type: str = "thesis"


@router.post("/orders")
async def create_order(body: OrderIn, db: AsyncSession = Depends(get_db),
                       user: CurrentUser = Depends(current_user)):
    if body.education not in _EDUCATIONS:
        raise HTTPException(422, f"education 必须是 {'/'.join(_EDUCATIONS)}")
    order = WritingOrder(
        tenant_id=user.tenant_id, owner_id=user.user_id,
        title=body.title, education=body.education,
        word_count=body.word_count, language=body.language,
        writing_type=body.writing_type,
        status="draft",
        price_cents=price_cents(body.education, body.word_count),  # 服务端算，忽略客户端价
    )
    db.add(order)
    await db.commit()
    return _order_out(order)


@router.get("/orders")
async def list_orders(db: AsyncSession = Depends(get_db),
                      user: CurrentUser = Depends(current_user)):
    query = ownership_filter(select(WritingOrder), WritingOrder, user)
    rows = (await db.execute(query)).scalars().all()
    return [_order_out(o) for o in rows]


@router.get("/orders/{order_id}")
async def get_order(order_id: str, db: AsyncSession = Depends(get_db),
                    user: CurrentUser = Depends(current_user)):
    return _order_out(await _get_owned_order(db, user, order_id))


@router.delete("/orders/{order_id}", status_code=204)
async def delete_order(order_id: str, db: AsyncSession = Depends(get_db),
                       user: CurrentUser = Depends(current_user)):
    order = await _get_owned_order(db, user, order_id)
    await db.delete(order)
    await db.commit()
    return Response(status_code=204)


# ── 大纲 ─────────────────────────────────────────────────────

class OutlineIn(BaseModel):
    feedback: str | None = Field(default=None, max_length=2000)


@router.post("/orders/{order_id}/outline")
async def gen_outline(order_id: str, body: OutlineIn | None = None,
                      wait: bool = Query(default=False),
                      db: AsyncSession = Depends(get_db),
                      user: CurrentUser = Depends(current_user)):
    order = await _get_owned_order(db, user, order_id)
    if order.status == "outlining":
        raise HTTPException(409, "大纲生成中，请稍候")

    remaining = await quota_remaining(db, user.user_id)
    if remaining <= 0:
        raise HTTPException(402, f"免费大纲次数已用尽（{settings.free_outline_limit} 次）")

    # 先扣后跑：append-only 台账 +1；失败在任务层退款
    db.add(QuotaLedger(
        tenant_id=user.tenant_id, user_id=user.user_id, kind="outline",
        delta=1, reason=f"大纲生成 order={order.id}",
        order_id=order.id,
    ))
    job = GenerationJob(
        tenant_id=user.tenant_id, order_id=order.id, kind="outline",
        result_json={"feedback": (body.feedback if body else None)},
    )
    db.add(job)
    await db.commit()

    if wait:
        await run_job(job.id)
        await db.refresh(job)
        await db.refresh(order)
        if job.status == "failed":
            raise HTTPException(502, f"大纲生成失败：{job.error}")
        return {"job": _job_out(job), "order": _order_out(order)}
    launch(job.id)
    return {"job_id": job.id, "status": "queued"}


@router.get("/orders/{order_id}/outline")
async def get_outline(order_id: str, db: AsyncSession = Depends(get_db),
                      user: CurrentUser = Depends(current_user)):
    await _get_owned_order(db, user, order_id)
    row = (await db.execute(
        select(OrderOutline).where(OrderOutline.order_id == order_id)
        .order_by(OrderOutline.version.desc()).limit(1)
    )).scalar()
    if row is None:
        raise HTTPException(404, "还没有大纲")
    return {"version": row.version, "content_md": row.content_md}


# ── 章节 ─────────────────────────────────────────────────────

@router.get("/orders/{order_id}/chapters")
async def list_chapters(order_id: str, db: AsyncSession = Depends(get_db),
                        user: CurrentUser = Depends(current_user)):
    await _get_owned_order(db, user, order_id)
    rows = (await db.execute(
        select(OrderChapter).where(OrderChapter.order_id == order_id)
        .order_by(OrderChapter.idx)
    )).scalars().all()
    return [_chapter_out(c) for c in rows]


@router.post("/orders/{order_id}/chapters/{node_id}")
async def gen_chapter(order_id: str, node_id: str, wait: bool = Query(default=False),
                      db: AsyncSession = Depends(get_db),
                      user: CurrentUser = Depends(current_user)):
    order = await _get_owned_order(db, user, order_id)
    if order.status not in ("outline_done", "writing", "writing_done"):
        raise HTTPException(409, "请先生成大纲")
    if order.paid_at is None:
        # 对照原产品付费流：大纲免费，正文生成需支付解锁
        raise HTTPException(402, "订单尚未支付，正文生成需先完成支付（POST /payments/orders/{id}）")
    chapter = (await db.execute(
        select(OrderChapter).where(
            OrderChapter.order_id == order_id, OrderChapter.node_id == node_id)
    )).scalar()
    if chapter is None:
        raise HTTPException(404, "章节不存在")
    if chapter.status == "writing":
        raise HTTPException(409, "该章节生成中，请稍候")

    job = GenerationJob(tenant_id=user.tenant_id, order_id=order_id,
                        kind="chapter", node_id=node_id)
    db.add(job)
    chapter.status = "writing"
    await db.commit()

    if wait:
        await run_job(job.id)
        await db.refresh(job)
        await db.refresh(chapter)
        if job.status == "failed":
            raise HTTPException(502, f"章节生成失败：{job.error}")
        return {"job": _job_out(job), "chapter": _chapter_out(chapter)}
    launch(job.id)
    return {"job_id": job.id, "status": "queued"}


class ChapterEditIn(BaseModel):
    content_md: str
    ai_level: str | None = None  # 显式声明层级；缺省按「编辑过 AI 稿」规则推断


@router.put("/orders/{order_id}/chapters/{node_id}")
async def edit_chapter(order_id: str, node_id: str, body: ChapterEditIn,
                       db: AsyncSession = Depends(get_db),
                       user: CurrentUser = Depends(current_user)):
    order = await _get_owned_order(db, user, order_id)
    chapter = (await db.execute(
        select(OrderChapter).where(
            OrderChapter.order_id == order_id, OrderChapter.node_id == node_id)
    )).scalar()
    if chapter is None:
        raise HTTPException(404, "章节不存在")

    chapter.content_md = body.content_md
    chapter.word_count = count_words(body.content_md)
    chapter.status = "done"
    if body.ai_level:
        if body.ai_level not in ("A", "B", "C"):
            raise HTTPException(422, "ai_level 必须是 A/B/C")
        chapter.ai_level = body.ai_level
    elif chapter.ai_level == "A":
        chapter.ai_level = "B"  # AI 初稿被人工修改 → 层级自动升级（如实披露）

    remaining = (await db.execute(
        select(OrderChapter).where(
            OrderChapter.order_id == order_id, OrderChapter.status != "done")
    )).scalars().all()
    if not remaining and order.status in ("writing", "writing_done"):
        order.status = "writing_done"
    await db.commit()
    return _chapter_out(chapter)


# ── 章节降重/改写 ────────────────────────────────────────────

class RewriteIn(BaseModel):
    instruction: str = Field(default="", max_length=500)


@router.post("/orders/{order_id}/chapters/{node_id}/rewrite")
async def rewrite_chapter(order_id: str, node_id: str, body: RewriteIn | None = None,
                          wait: bool = Query(default=True),
                          db: AsyncSession = Depends(get_db),
                          user: CurrentUser = Depends(current_user)):
    order = await _get_owned_order(db, user, order_id)
    if order.paid_at is None:
        raise HTTPException(402, "订单尚未支付，改写需先完成支付（POST /payments/orders/{id}）")
    chapter = (await db.execute(
        select(OrderChapter).where(
            OrderChapter.order_id == order_id, OrderChapter.node_id == node_id)
    )).scalar()
    if chapter is None:
        raise HTTPException(404, "章节不存在")
    if not chapter.content_md:
        raise HTTPException(409, "该章节还没有内容，先生成正文")

    job = GenerationJob(
        tenant_id=user.tenant_id, order_id=order_id, kind="rewrite",
        node_id=node_id,
        result_json={"instruction": body.instruction if body else ""},
    )
    db.add(job)
    await db.commit()

    if wait:
        await run_job(job.id)
        await db.refresh(job)
        await db.refresh(chapter)
        if job.status == "failed":
            raise HTTPException(502, f"改写失败：{job.error}")
        return {"job": _job_out(job), "chapter": _chapter_out(chapter)}
    launch(job.id)
    return {"job_id": job.id, "status": "queued"}


# ── 导出 ─────────────────────────────────────────────────────

@router.post("/orders/{order_id}/export")
async def export_order(order_id: str, profile: str = Query(default="default"),
                       db: AsyncSession = Depends(get_db),
                       user: CurrentUser = Depends(current_user)):
    order = await _get_owned_order(db, user, order_id)
    chapters = (await db.execute(
        select(OrderChapter).where(OrderChapter.order_id == order_id)
        .order_by(OrderChapter.idx)
    )).scalars().all()
    if not chapters:
        raise HTTPException(409, "还没有章节，先生成大纲")
    pending = [c for c in chapters if c.status != "done"]
    if pending:
        raise HTTPException(409, f"还有 {len(pending)} 个章节未完成，不能导出")

    data = build_thesis_docx(
        title=order.title, education=order.education,
        chapters=[{
            "idx": c.idx, "node_id": c.node_id, "title": c.title,
            "content_md": c.content_md, "word_count": c.word_count,
            "ai_level": c.ai_level,
        } for c in chapters],
        language=order.language,
    )
    if profile != "default":
        try:
            from ..export.formatter import apply_format_profile
            data = apply_format_profile(data, profile)
        except KeyError:
            raise HTTPException(
                422, f"未知格式 profile：{profile}；可用值见 GET /formatting/profiles") from None
    order.status = "exported"
    await db.commit()
    filename = quote(f"{order.title}.docx")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
