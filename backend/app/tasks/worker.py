"""arq worker：大纲/逐章/核查的长任务。生成类一律异步 + 前端轮询（逆向还原的状态机）。

启动：arq app.tasks.worker.WorkerSettings
"""
from arq.connections import RedisSettings

from ..config import settings


async def ctx_info(ctx) -> str:
    return f"worker={ctx.get('worker_name', '?')}"


async def run_job_task(ctx, job_id: str) -> dict:
    """arq 入口：与内联模式共用同一份执行逻辑（tasks/local.run_job）。"""
    from .local import run_job

    await run_job(job_id)
    return {"job_id": job_id, "worker": ctx.get("worker_name", "?")}


async def outline_task(ctx, order_id: str) -> dict:
    """大纲生成。移植自 thesis_auto_generator 的大纲 prompt（见 PORTING.md §2）。

    TODO(v0.2):
    1. 读订单（校验 tenant+owner，配额扣减走 billing.consume_quota）
    2. 组 prompt（app/prompts/outline.txt）
    3. get_provider().complete(...)，结果写 order_outlines 表
    4. 返回 {"outline": [...], "usage": {...}}
    """
    raise NotImplementedError("v0.2 移植 thesis_auto_generator 大纲链路")


async def chapter_task(ctx, order_id: str, chapter_index: int) -> dict:
    """逐章正文生成。TODO(v0.2)：大纲上下文 + 章节指令 → 正文 + A/B/C 参与度标记。"""
    raise NotImplementedError("v0.2 移植逐章生成")


class WorkerSettings:
    functions = [run_job_task, outline_task, chapter_task]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 4
