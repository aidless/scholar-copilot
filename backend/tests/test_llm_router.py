"""v1.11 #22：多模型路由与降级 + 成本对比。"""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_routes(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "llm_routes", "")
    monkeypatch.setattr(settings, "llm_fallback_models", "")
    monkeypatch.setattr(settings, "llm_model", "deepseek-chat")
    monkeypatch.setattr(settings, "llm_provider", "fake")
    yield


def test_default_chain_from_model_and_fallback(monkeypatch):
    from app.config import settings
    from app.llm.router import routes_for
    monkeypatch.setattr(settings, "llm_fallback_models", "qwen-plus,gpt-4o-mini")
    assert routes_for("outline") == ["deepseek-chat", "qwen-plus", "gpt-4o-mini"]
    # 未配置 fallback 时只有主模型
    monkeypatch.setattr(settings, "llm_fallback_models", "")
    assert routes_for("outline") == ["deepseek-chat"]


def test_routes_json_overrides_per_task(monkeypatch):
    from app.config import settings
    from app.llm.router import routes_for
    monkeypatch.setattr(settings, "llm_routes", json.dumps(
        {"outline": ["qwen-max", "deepseek-chat"], "default": ["deepseek-chat"]}))
    assert routes_for("outline") == ["qwen-max", "deepseek-chat"]
    assert routes_for("chapter") == ["deepseek-chat"]


def test_invalid_routes_json_falls_back(monkeypatch):
    from app.config import settings
    from app.llm.router import routes_for
    monkeypatch.setattr(settings, "llm_routes", "{not json")
    assert routes_for("outline") == ["deepseek-chat"]


@pytest.mark.anyio
async def test_fallback_on_primary_failure(monkeypatch):
    from app import llm
    from app.llm import router as r

    calls = []

    class Boom:
        async def complete(self, *a, **k):
            calls.append("boom")
            raise RuntimeError("primary down")

    class Ok:
        async def complete(self, *a, **k):
            calls.append("ok")
            from app.llm.base import LLMResult
            return LLMResult(text="degraded ok", prompt_tokens=3, completion_tokens=4, model="qwen-plus")

    from app.config import settings
    monkeypatch.setattr(settings, "llm_fallback_models", "qwen-plus")
    monkeypatch.setattr(r, "_provider_for_model", lambda m: Boom() if m == "deepseek-chat" else Ok())
    res = await r.complete_for("outline", "hi")
    assert res.text == "degraded ok"
    assert res.model == "qwen-plus"
    assert calls == ["boom", "ok"]


@pytest.mark.anyio
async def test_all_fail_raises_with_attempts(monkeypatch):
    from app.llm import router as r

    class Boom:
        async def complete(self, *a, **k):
            raise RuntimeError("down")

    monkeypatch.setattr(r, "_provider_for_model", lambda m: Boom())
    with pytest.raises(RuntimeError) as exc:
        await r.complete_for("outline", "hi")
    assert "deepseek-chat" in str(exc.value)
    assert "RuntimeError" in str(exc.value)


def test_estimate_cost_uses_table():
    from app.llm.router import estimate_cost
    # deepseek-chat: 0.001/千输入, 0.002/千输出
    assert estimate_cost("deepseek-chat", 1000, 1000) == pytest.approx(0.003)
    assert estimate_cost("fake-model", 1000, 1000) == 0.0
    # 未知模型用兜底单价（不报错）
    assert estimate_cost("unknown-model", 1000, 0) > 0


def test_models_endpoints():
    from app.main import create_app
    client = TestClient(create_app())
    r = client.get("/tools/models")
    assert r.status_code == 200
    data = r.json()
    assert "outline" in data["tasks"]
    assert "deepseek-chat" in data["costs_per_1k"]
    r = client.post("/tools/models/cost",
                    json={"task": "outline", "tokens_in": 1000, "tokens_out": 1000})
    assert r.status_code == 200
    rows = r.json()["options"]
    assert rows[0]["cost_cny"] <= rows[-1]["cost_cny"]  # 按成本升序
