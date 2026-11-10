"""job 轮询端点 + WebSocket 进度推送。属主校验经订单（job 表无 owner 列，避免冗余）。"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
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


@router.websocket("/{job_id}/ws")
async def job_ws(websocket: WebSocket, job_id: str, token: str = ""):
    """进度推送：连接后每 1s 推一次状态，终态后关闭。

    鉴权走查询参数 token（浏览器 WebSocket 无法带 Authorization 头），
    属主校验同 REST：订单不属于你 → 直接以 1008 关闭，不泄露任务是否存在。
    """
    from ..db import _engine_and_session
    from ..security import parse_token

    await websocket.accept()
    try:
        payload = parse_token(token)
        user_id, tenant_id = payload["sub"], payload.get("tid", "primary")
    except Exception:  # noqa: BLE001——token 无效
        await websocket.close(code=1008)
        return

    try:
        while True:
            async with _engine_and_session()[1]() as db:
                job = await db.get(GenerationJob, job_id)
                if job is None:
                    await websocket.close(code=1008)
                    return
                order = (await db.execute(
                    select(WritingOrder).where(WritingOrder.id == job.order_id,
                                               WritingOrder.tenant_id == tenant_id,
                                               WritingOrder.owner_id == user_id)
                )).scalar()
                if order is None:
                    await websocket.close(code=1008)
                    return
                snapshot = _job_out(job)
            await websocket.send_json(snapshot)
            if snapshot["status"] in ("done", "failed"):
                await websocket.close()
                return
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
