"""限流：默认进程内滑动窗口，可选 Redis 共享（多实例部署）。

为什么要有两个后端（2026-11-10 实测教训）：
进程内计数在 `--workers 2` 或多副本部署下形同虚设——每个进程各算一份，
真实配额 = 配置值 × 实例数。撞库/短信轰炸防护因此必须能共享计数。

后端选择 `SC_RATE_LIMIT_BACKEND`：
- `memory`（默认）：零依赖，单实例够用；测试也走这条。
- `redis`：sorted set 滑动窗口，多实例共享。Redis 不可用时**降级为进程内**并打警告
  （限流是防护层不是正确性层：降级成「每个实例各自限流」比整站 500 更合理，
  但必须在日志里显式可见，不能静默）。

窗口语义两个后端保持一致：窗口内第 limit+1 次请求 → 429 + `Retry-After`（秒）。
"""
import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from .config import settings

log = logging.getLogger(__name__)

# {key: deque[timestamp]}——memory 后端
_WINDOWS: dict[str, deque] = defaultdict(deque)

# 惰性创建，避免导入期就连 Redis（测试与无 Redis 环境不该被卡住）
_redis_client = None


def _client():
    global _redis_client
    if _redis_client is None:
        from redis.asyncio import from_url

        _redis_client = from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def _too_many(retry: int) -> HTTPException:
    return HTTPException(429, f"请求过于频繁，请 {retry} 秒后再试",
                         headers={"Retry-After": str(retry)})


def _hit(key: str, limit: int, window_seconds: int) -> None:
    """memory 后端：进程内滑动窗口。"""
    if limit <= 0:
        return
    now = time.monotonic()
    q = _WINDOWS[key]
    while q and now - q[0] > window_seconds:
        q.popleft()
    if len(q) >= limit:
        raise _too_many(int(window_seconds - (now - q[0])) + 1)
    q.append(now)


async def _hit_redis(key: str, limit: int, window_seconds: int) -> None:
    """redis 后端：sorted set 滑动窗口（score = 毫秒时间戳，member 唯一）。

    用 pipeline 把「清理过期 → 计数 → 写入 → 续期」压成一次往返；
    判超限在读之前算，保证第 limit+1 次一定被拒。
    """
    if limit <= 0:
        return
    now_ms = int(time.time() * 1000)
    cutoff = now_ms - window_seconds * 1000
    rkey = f"rl:{key}"
    try:
        cli = _client()
        pipe = cli.pipeline()
        pipe.zremrangebyscore(rkey, 0, cutoff)
        pipe.zcard(rkey)
        _, count = await pipe.execute()
        if count >= limit:
            oldest = await cli.zrange(rkey, 0, 0, withscores=True)
            retry = window_seconds
            if oldest:
                retry = max(int((oldest[0][1] + window_seconds * 1000 - now_ms) / 1000) + 1, 1)
            raise _too_many(retry)
        pipe = cli.pipeline()
        # member 必须唯一：同一毫秒内多次请求若 member 相同会被 zadd 覆盖，计数失真
        pipe.zadd(rkey, {f"{now_ms}-{uuid.uuid4().hex[:8]}": now_ms})
        pipe.expire(rkey, window_seconds + 1)
        await pipe.execute()
    except HTTPException:
        raise
    except Exception as exc:  # Redis 挂掉：降级进程内，但必须留痕
        log.warning("限流 Redis 后端不可用（%s），本次降级为进程内计数：%s", type(exc).__name__, exc)
        _hit(key, limit, window_seconds)


async def _check(key: str, limit: int, window_seconds: int) -> None:
    if settings.rate_limit_backend == "redis":
        await _hit_redis(key, limit, window_seconds)
    else:
        _hit(key, limit, window_seconds)


def _ip(request: Request) -> str:
    return (request.client.host if request.client else "unknown")


async def rate_limit_login(request: Request) -> None:
    """登录/注册/短信：按 IP。抗撞库、抗短信轰炸。"""
    await _check(f"login:{_ip(request)}", settings.rate_limit_login_per_minute, 60)


async def rate_limit_llm(request: Request) -> None:
    """LLM 昂贵端点：按 IP（未登录也可被刷，故不依赖 user 身份）。"""
    await _check(f"llm:{_ip(request)}", settings.rate_limit_llm_per_minute, 60)


async def rate_limit_search(request: Request) -> None:
    """公开检索：按 IP。保护上游 Crossref/OpenAlex 配额。"""
    await _check(f"search:{_ip(request)}", settings.rate_limit_search_per_minute, 60)


def reset_all() -> None:
    """测试用：清空进程内计数（Redis 后端由测试自行 flush）。"""
    _WINDOWS.clear()
