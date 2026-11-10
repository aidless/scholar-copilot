"""任务队列抽象：inline（默认，asyncio 进程内）或 arq（Redis，多实例部署）。

端点只调 `await enqueue(job_id)`——部署时改一个环境变量 SC_TASK_QUEUE=arq
就能把生成任务交给独立 worker 进程，端点行为不变（仍是 202 + 轮询 /jobs/{id}）。
"""
from ..config import settings
from . import local

_POOL = None


async def _get_pool():
    global _POOL
    if _POOL is None:
        from arq import create_pool
        from arq.connections import RedisSettings

        _POOL = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _POOL


async def enqueue(job_id: str) -> str:
    """投递任务，返回实际使用的通道名（便于日志/测试断言）。"""
    if settings.task_queue == "arq":
        pool = await _get_pool()
        await pool.enqueue_job("run_job_task", job_id)
        return "arq"
    local.launch(job_id)
    return "inline"
