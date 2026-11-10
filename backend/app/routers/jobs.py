"""job 轮询端点。属主校验经订单（job 表无 owner 列，避免冗余）。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import GenerationJob, WritingOrder
from ..tenancy import CurrentUser, current_user, ownership_filter

router = APIRouter(prefix="/jobs", tags=["jobs"])


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
        "order_id": job.order_id,
    }


@router.get("/{job_id}")
async def get_job(job_id: str, db: AsyncSession = Depends(get_db),
                  user: CurrentUser = Depends(current_user)):
    job = await db.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    order = (await db.execute(
        ownership_filter(select(WritingOrder), WritingOrder, user)
        .where(WritingOrder.id == job.order_id)
    )).scalar()
    if order is None:  # 不是你的订单 → 统一 404
        raise HTTPException(404, "任务不存在")
    return _job_out(job)
