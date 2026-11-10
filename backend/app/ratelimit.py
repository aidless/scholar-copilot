"""进程内滑动窗口限流（无额外依赖，多实例部署时换 Redis 实现）。

设计：按 (key, 路由标签) 计数，窗口内超限返回 429 + Retry-After。
默认策略（可在 Settings 调整）：
- login/register：20 次/分钟/IP —— 抗撞库
- tools/rewrite 等 LLM 端点：10 次/分钟/用户，另加每日 200 次
- 公开检索：30 次/分钟/IP
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from .config import settings

# {key: deque[timestamp]}
_WINDOWS: dict[str, deque] = defaultdict(deque)


def _hit(key: str, limit: int, window_seconds: int) -> None:
    """记一次命中；超限抛 429（含 Retry-After）。"""
    if limit <= 0:
        return
    now = time.monotonic()
    q = _WINDOWS[key]
    while q and now - q[0] > window_seconds:
        q.popleft()
    if len(q) >= limit:
        retry = int(window_seconds - (now - q[0])) + 1
        raise HTTPException(429, f"请求过于频繁，请 {retry} 秒后再试",
                            headers={"Retry-After": str(retry)})
    q.append(now)


def _ip(request: Request) -> str:
    return (request.client.host if request.client else "unknown")


def rate_limit_login(request: Request) -> None:
    """登录/注册/短信：按 IP。抗撞库、抗短信轰炸。"""
    _hit(f"login:{_ip(request)}", settings.rate_limit_login_per_minute, 60)


def rate_limit_llm(request: Request) -> None:
    """LLM 昂贵端点：按 IP（未登录也可被刷，故不依赖 user 身份）。"""
    _hit(f"llm:{_ip(request)}", settings.rate_limit_llm_per_minute, 60)


def rate_limit_search(request: Request) -> None:
    """公开检索：按 IP。保护上游 Crossref/OpenAlex 配额。"""
    _hit(f"search:{_ip(request)}", settings.rate_limit_search_per_minute, 60)


def reset_all() -> None:
    """测试用：清空全部计数。"""
    _WINDOWS.clear()
