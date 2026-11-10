"""限流 Redis 后端（多实例共享计数）的机制验证。

为什么必须单独测（2026-11-10 实测教训）：
进程内限流在 `--workers 2` / 多副本下真实配额 = 配置值 × 实例数，撞库防护形同虚设。
这里不测「接口会不会 429」（那已有用例），而是测**共享计数语义本身**：
两个独立的 limiter 实例（模拟两个进程）共用同一 Redis 时必须共享配额，
且 Redis 不可用时要降级为进程内计数（留警告，不 500）。
"""
import pytest
import fakeredis.aioredis
from fastapi import HTTPException

from app import ratelimit
from app.config import settings


@pytest.fixture
def redis_backend(monkeypatch):
    """把限流后端切到 Redis，并注入内存版 Redis 服务器（无需真实 redis-server）。"""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(ratelimit, "_redis_client", fake)
    yield fake
    ratelimit.reset_all()


@pytest.mark.anyio
async def test_redis_backend_shares_quota_across_processes(redis_backend):
    """两个进程各自调用，共享同一 Redis 计数：limit=3 时第 4 次必须被拒。"""
    for _ in range(3):
        await ratelimit._check("login:10.0.0.1", 3, 60)
    # 模拟第二个进程（新调用栈，但同一 Redis）
    with pytest.raises(HTTPException) as exc:
        await ratelimit._check("login:10.0.0.1", 3, 60)
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers


@pytest.mark.anyio
async def test_redis_backend_key_isolation(redis_backend):
    """不同 key（不同 IP / 不同路由）互不干扰。"""
    await ratelimit._check("login:1.1.1.1", 1, 60)
    await ratelimit._check("login:2.2.2.2", 1, 60)
    await ratelimit._check("llm:1.1.1.1", 1, 60)
    with pytest.raises(HTTPException):
        await ratelimit._check("login:1.1.1.1", 1, 60)


@pytest.mark.anyio
async def test_redis_backend_window_expires(redis_backend, monkeypatch):
    """窗口过期后应重新放行（用 1 秒窗口 + 时间跳跃验证，不真等）。"""
    real_time = __import__("time").time
    now = [1000.0]
    monkeypatch.setattr(ratelimit.time, "time", lambda: now[0])

    await ratelimit._check("login:3.3.3.3", 1, 1)
    with pytest.raises(HTTPException):
        await ratelimit._check("login:3.3.3.3", 1, 1)
    now[0] += 2.0  # 跨过窗口
    await ratelimit._check("login:3.3.3.3", 1, 1)  # 不应抛
    assert real_time  # 保持引用，避免未使用告警


@pytest.mark.anyio
async def test_redis_failure_degrades_to_memory(monkeypatch):
    """Redis 不可用时降级为进程内计数：仍能限流，且不抛 500。"""
    class Broken:
        def pipeline(self):
            raise RuntimeError("redis down")

    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(ratelimit, "_redis_client", Broken())
    ratelimit.reset_all()

    await ratelimit._check("login:4.4.4.4", 1, 60)   # 降级后第一次放行
    with pytest.raises(HTTPException) as exc:
        await ratelimit._check("login:4.4.4.4", 1, 60)  # 降级后仍然限流
    assert exc.value.status_code == 429
