"""任务执行：大纲/章节生成 job。

v0.2 用 asyncio（端点 ?wait=true 内联等待，否则 create_task 后台跑），
无需 Redis；v0.5 多实例部署时换 arq（tasks/worker.py 已留壳）。
配额纪律：消耗在端点侧（先查后扣），失败在本模块退款 delta=-1。
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from ..db import _engine_and_session
from ..llm.registry import get_provider
from ..models import GenerationJob, OrderChapter, OrderOutline, QuotaLedger, WritingOrder
from ..prompts.chapter_prompts import (
    CHAPTER_SYSTEM_PROMPT,
    build_chapter_user_prompt,
)
from ..prompts.outline_prompts import (
    OUTLINE_FEEDBACK_SYSTEM_PROMPT,
    OUTLINE_SYSTEM_PROMPT,
    build_outline_feedback_prompt,
    build_outline_user_prompt,
)
from ..prompts.rewrite_prompts import REWRITE_SYSTEM_PROMPT, build_rewrite_user_prompt
from ..writing.outline_parser import get_chapters, parse_outline_markdown
from ..writing.service import count_words

log = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc)


def launch(job_id: str) -> None:
    """后台执行（fire-and-forget，异常在 run_job 内兜底）。"""
    asyncio.create_task(run_job(job_id))


async def run_job(job_id: str) -> None:
    engine, SessionLocal = _engine_and_session()
    async with SessionLocal() as db:
        job = await db.get(GenerationJob, job_id)
        if job is None or job.status != "queued":
            return
        job.status = "running"
        job.progress = 5
        await db.commit()
        try:
            if job.kind == "outline":
                await _run_outline(db, job)
            elif job.kind == "chapter":
                await _run_chapter(db, job)
            elif job.kind == "rewrite":
                await _run_rewrite(db, job)
            else:
                raise ValueError(f"未知任务类型：{job.kind}")
            job.status = "done"
            job.progress = 100
            job.finished_at = _now()
            await db.commit()
        except Exception as exc:  # noqa: BLE001——任务失败必须落库而非炸进程
            log.exception("job %s failed", job_id)
            await db.rollback()
            await _mark_failed(db, job_id, str(exc))


async def _mark_failed(db, job_id: str, error: str) -> None:
    job = await db.get(GenerationJob, job_id)
    if job is None:
        return
    job.status = "failed"
    job.error = error[:2000]
    job.finished_at = _now()
    if job.kind == "outline":
        order = await db.get(WritingOrder, job.order_id)
        if order is not None:
            db.add(QuotaLedger(
                tenant_id=order.tenant_id, user_id=order.owner_id,
                kind="outline", delta=-1,
                reason=f"outline 生成失败退款 job={job_id}",
                order_id=order.id,
            ))
    await db.commit()


async def _run_outline(db, job: GenerationJob) -> None:
    order = await db.get(WritingOrder, job.order_id)
    if order is None:
        raise ValueError(f"订单不存在：{job.order_id}")
    order.status = "outlining"
    await db.commit()

    # 最新大纲版本（反馈再生时作为上下文）
    prev = (await db.execute(
        select(OrderOutline).where(OrderOutline.order_id == order.id)
        .order_by(OrderOutline.version.desc()).limit(1)
    )).scalar()

    feedback = (job.result_json or {}).get("feedback")
    if feedback and prev is not None:
        system = OUTLINE_FEEDBACK_SYSTEM_PROMPT
        user_prompt = build_outline_feedback_prompt(prev.content_md, feedback)
    else:
        system = OUTLINE_SYSTEM_PROMPT
        user_prompt = build_outline_user_prompt(
            topic=order.title, keywords=[], discipline=order.education,
            target_word_count=order.word_count,
        )

    job.progress = 30
    await db.commit()

    provider = get_provider()
    result = await provider.complete(user_prompt, system=system, max_tokens=8192)
    tree = parse_outline_markdown(result.text)  # 解析失败 → job failed + 退款
    chapter_nodes = get_chapters(tree)

    version = (prev.version + 1) if prev is not None else 1
    db.add(OrderOutline(
        tenant_id=order.tenant_id, order_id=order.id, version=version,
        content_md=result.text, tree_json=tree,
    ))

    # 重置章节骨架：新大纲覆盖旧章节（含已生成内容），按 level1 节点重建
    old_chapters = (await db.execute(
        select(OrderChapter).where(OrderChapter.order_id == order.id)
    )).scalars().all()
    for ch in old_chapters:
        await db.delete(ch)
    await db.flush()

    for i, node in enumerate(chapter_nodes):
        db.add(OrderChapter(
            tenant_id=order.tenant_id, order_id=order.id,
            node_id=node["id"], idx=i + 1, level=1,
            title=node["title"], description=node.get("content", ""),
            status="pending", ai_level="C", word_count=0,
        ))

    order.status = "outline_done"
    job.result_json = {"version": version, "chapters": len(chapter_nodes)}
    job.tokens_in = result.prompt_tokens
    job.tokens_out = result.completion_tokens
    job.model = result.model
    await db.commit()


async def _run_chapter(db, job: GenerationJob) -> None:
    order = await db.get(WritingOrder, job.order_id)
    if order is None:
        raise ValueError(f"订单不存在：{job.order_id}")
    chapter = (await db.execute(
        select(OrderChapter).where(
            OrderChapter.order_id == order.id, OrderChapter.node_id == job.node_id)
    )).scalar()
    if chapter is None:
        raise ValueError(f"章节不存在：{job.node_id}")
    chapter.status = "writing"
    await db.commit()

    outline = (await db.execute(
        select(OrderOutline).where(OrderOutline.order_id == order.id)
        .order_by(OrderOutline.version.desc()).limit(1)
    )).scalar()
    if outline is None:
        raise ValueError("订单还没有大纲，先生成大纲")

    # 前序已完成章节摘要（每章前 200 字）
    prev_rows = (await db.execute(
        select(OrderChapter).where(
            OrderChapter.order_id == order.id,
            OrderChapter.idx < chapter.idx, OrderChapter.status == "done")
        .order_by(OrderChapter.idx)
    )).scalars().all()
    summary_lines = []
    for row in prev_rows:
        preview = (row.content_md or "")[:200].replace("\n", " ")
        summary_lines.append(f"**{row.title}**（{row.word_count} 字）\n> {preview}...")
    prev_summary = "\n".join(summary_lines)

    all_chapters = (await db.execute(
        select(OrderChapter).where(OrderChapter.order_id == order.id)
    )).scalars().all()
    target = max(order.word_count // max(len(all_chapters), 1), 300)

    user_prompt = build_chapter_user_prompt(
        chapter_title=chapter.title,
        chapter_description=chapter.description,
        full_outline_md=outline.content_md,
        target_word_count=target,
        prev_chapters_summary=prev_summary,
    )

    job.progress = 30
    await db.commit()
    provider = get_provider()
    result = await provider.complete(user_prompt, system=CHAPTER_SYSTEM_PROMPT, max_tokens=8192)

    chapter.content_md = result.text
    chapter.word_count = count_words(result.text)
    chapter.status = "done"
    chapter.ai_level = "A"  # 生成即 AI 未经修改；用户编辑后端点自动升 B

    remaining = (await db.execute(
        select(OrderChapter).where(
            OrderChapter.order_id == order.id, OrderChapter.status != "done")
    )).scalars().all()
    order.status = "writing_done" if not remaining else "writing"

    job.result_json = {"node_id": chapter.node_id, "word_count": chapter.word_count}
    job.tokens_in = result.prompt_tokens
    job.tokens_out = result.completion_tokens
    job.model = result.model
    await db.commit()


async def _run_rewrite(db, job: GenerationJob) -> None:
    """章节降重/改写：语义=AI 改写后仍是 AI 产出，披露层级如实更新。

    A/B（AI 产出）→ 改写后仍 A；C（人工撰写）被 AI 改写 → 如实升 B。
    """
    chapter = (await db.execute(
        select(OrderChapter).where(
            OrderChapter.order_id == job.order_id, OrderChapter.node_id == job.node_id)
    )).scalar()
    if chapter is None:
        raise ValueError(f"章节不存在：{job.node_id}")
    if not chapter.content_md:
        raise ValueError("该章节还没有内容，无法改写")

    prev_level = chapter.ai_level
    instruction = (job.result_json or {}).get("instruction", "")
    job.progress = 30
    await db.commit()

    provider = get_provider()
    result = await provider.complete(
        build_rewrite_user_prompt(chapter.content_md, instruction),
        system=REWRITE_SYSTEM_PROMPT, max_tokens=8192,
    )
    chapter.content_md = result.text
    chapter.word_count = count_words(result.text)
    chapter.ai_level = "A" if prev_level in ("A", "B") else "B"

    job.result_json = {
        "node_id": chapter.node_id, "word_count": chapter.word_count,
        "prev_ai_level": prev_level, "ai_level": chapter.ai_level,
    }
    job.tokens_in = result.prompt_tokens
    job.tokens_out = result.completion_tokens
    job.model = result.model
    await db.commit()
