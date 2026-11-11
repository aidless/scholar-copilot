"""多模型路由与降级（v1.11 #22）。

原产品模型锁死一家；本项目虽已把 provider 做成可插拔，但仍是「一个 model 打天下」。
这里补上：
1. 按任务种类（outline/chapter/abstract/rewrite/...）配置模型优先级链；
2. 主模型失败自动降级到下一个（异常/超时都算失败），全部失败才抛错且带上尝试记录；
3. 成本表（元/千 token），供「同任务不同模型的预估成本」比较。

路由来源优先级：
- `SC_LLM_ROUTES`（JSON，形如 {"outline":["deepseek-chat","qwen-plus"],"default":["deepseek-chat"]}）
- 否则用 `SC_LLM_MODEL` + `SC_LLM_FALLBACK_MODELS`（逗号分隔）拼默认链
- `SC_LLM_PROVIDER=fake` 时始终走 FakeProvider（测试/离线确定性）
"""
from __future__ import annotations

import json
import logging

from ..config import settings
from .base import LLMProvider, LLMResult
from .fake import FakeProvider
from .openai_compat import OpenAICompatProvider

log = logging.getLogger(__name__)

TASK_KINDS = ("outline", "chapter", "abstract", "rewrite", "diagram", "ppt", "default")

# 成本表：元 / 千 token（输入, 输出）。用于「成本对比」，非账单口径。
COST_TABLE: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.001, 0.002),
    "deepseek-reasoner": (0.004, 0.016),
    "qwen-plus": (0.0008, 0.002),
    "qwen-max": (0.0024, 0.0096),
    "gpt-4o-mini": (0.0011, 0.0044),
    "gpt-4o": (0.018, 0.072),
    "fake-model": (0.0, 0.0),
}
_DEFAULT_COST = (0.002, 0.006)


def _parse_routes() -> dict[str, list[str]]:
    routes: dict[str, list[str]] = {}
    raw = (getattr(settings, "llm_routes", "") or "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, list) and v:
                        routes[k] = [str(m) for m in v]
        except (ValueError, TypeError):
            log.warning("SC_LLM_ROUTES 不是合法 JSON，忽略：%s", raw[:80])
    fallback: list[str] = []
    fb = (getattr(settings, "llm_fallback_models", "") or "").strip()
    if fb:
        fallback = [m.strip() for m in fb.split(",") if m.strip()]
    default_chain = [settings.llm_model] + fallback
    for kind in TASK_KINDS:
        routes.setdefault(kind, list(default_chain))
    # 显式 default 覆盖未被单独指定的任务
    if routes.get("default"):
        for kind in TASK_KINDS:
            if kind not in routes or not routes[kind]:
                routes[kind] = list(routes["default"])
    return routes


def routes_for(task: str) -> list[str]:
    return _parse_routes().get(task) or _parse_routes().get("default") or [settings.llm_model]


def _provider_for_model(model: str) -> LLMProvider:
    if settings.llm_provider == "fake":
        return FakeProvider()
    return OpenAICompatProvider(model=model)


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """预估成本（元）。未知模型用兜底单价。"""
    ci, co = COST_TABLE.get(model, _DEFAULT_COST)
    return round(tokens_in / 1000 * ci + tokens_out / 1000 * co, 6)


async def complete_for(task: str, prompt: str, *, system: str = "",
                       max_tokens: int = 4096, temperature: float = 0.7) -> LLMResult:
    """按任务路由调用 LLM，主模型失败自动降级；返回结果并附 `model`。"""
    chain = routes_for(task)
    attempts: list[str] = []
    last_exc: Exception | None = None
    for model in chain:
        try:
            provider = _provider_for_model(model)
            result = await provider.complete(prompt, system=system,
                                             max_tokens=max_tokens, temperature=temperature)
            # 保证返回的 model 是本次路由选中的（fake/provider 可能不填）
            if not result.model:
                result.model = model
            return result
        except Exception as exc:  # noqa: BLE001 降级兜底
            attempts.append(f"{model}:{type(exc).__name__}")
            last_exc = exc
            log.warning("模型 %s 失败（%s），尝试降级", model, exc)
    raise RuntimeError(f"任务 {task} 所有模型均失败：{', '.join(attempts)}") from last_exc


def routing_table() -> dict:
    """给前端/运维看的：每任务模型链 + 成本表。"""
    routes = _parse_routes()
    return {
        "provider": settings.llm_provider,
        "tasks": routes,
        "costs_per_1k": {m: {"in": c[0], "out": c[1]} for m, c in COST_TABLE.items()},
    }
