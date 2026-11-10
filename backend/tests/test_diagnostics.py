"""启动自检的测试。

动机（实测场景）：clone 下来 `docker compose up -d`，SC_LLM_API_KEY 没填，
服务能起、页面能开、下单也成，**直到第一次生成才 401**，用户以为是代码坏了。
这类延迟暴露的配置错误必须在启动日志里说清楚。
"""
import pytest

from app.config import Settings
from app.diagnostics import startup_warnings


def _s(**kw) -> Settings:
    """构造一个「生产正确」的基线配置，再按用例覆盖单项。"""
    base = dict(
        llm_provider="openai_compat",
        llm_api_key="sk-real-key-value",
        sms_dev_mode=False,
        sms_provider="http",
        payment_mode="real",
        admin_initial_password="Str0ng-Pass",
        jwt_secret="a-very-long-random-secret-for-tests",
        database_url="postgresql+asyncpg://u:p@h:5432/d",
        db_auto_create=False,
        rate_limit_backend="redis",
        task_queue="arq",
    )
    base.update(kw)
    return Settings(**base)


def test_correct_config_has_no_warnings():
    """基线配置必须零警告，否则警告会被当噪音忽略。"""
    assert startup_warnings(_s()) == []


def test_missing_llm_key_warns():
    msgs = startup_warnings(_s(llm_api_key=""))
    assert len(msgs) == 1
    assert "SC_LLM_API_KEY" in msgs[0] and "401" not in msgs[0]
    # 必须给出两条出路，而不是只说「你错了」
    assert "fake" in msgs[0]


def test_placeholder_llm_key_warns():
    """占位符（sk-xxx / changeme / TODO）等价于没填——这是最常见的复制粘贴残留。"""
    for bad in ("sk-xxx", "changeme", "TODO", "   "):
        msgs = startup_warnings(_s(llm_api_key=bad))
        assert any("SC_LLM_API_KEY" in m for m in msgs), bad


def test_fake_provider_warns_about_demo_data():
    msgs = startup_warnings(_s(llm_provider="fake", llm_api_key=""))
    assert any("fake provider" in m for m in msgs)
    # fake 模式不应再抱怨密钥缺失（否则一次两条，噪音）
    assert not any("SC_LLM_API_KEY" in m for m in msgs)


def test_sms_dev_mode_warns_loudly():
    msgs = startup_warnings(_s(sms_dev_mode=True))
    assert any("000000" in m and "生产" in m for m in msgs)


def test_mock_payment_warns():
    msgs = startup_warnings(_s(payment_mode="mock"))
    assert any("SC_PAYMENT_MODE" in m for m in msgs)


def test_missing_admin_password_warns():
    msgs = startup_warnings(_s(admin_initial_password=""))
    assert any("SC_ADMIN_INITIAL_PASSWORD" in m for m in msgs)


@pytest.mark.parametrize("bad", ["", "change-me", "dev-secret", "test-secret"])
def test_default_jwt_secret_warns(bad):
    msgs = startup_warnings(_s(jwt_secret=bad))
    assert any("SC_JWT_SECRET" in m for m in msgs), bad


def test_autocreate_with_postgres_warns_double_source():
    msgs = startup_warnings(_s(db_auto_create=True))
    assert any("双真相源" in m for m in msgs)


def test_autocreate_with_sqlite_does_not_warn():
    """SQLite 场景（本地开发/测试）create_all 是正常用法，不该报警。"""
    msgs = startup_warnings(_s(db_auto_create=True,
                               database_url="sqlite+aiosqlite:///./dev.db"))
    assert not any("双真相源" in m for m in msgs)


def test_memory_ratelimit_with_arq_warns_quota_multiplied():
    """多进程 + 进程内限流 = 配额按容器数放大，这条在 v1.5 是真实踩过的坑。"""
    msgs = startup_warnings(_s(rate_limit_backend="memory", task_queue="arq"))
    assert any("SC_RATE_LIMIT_BACKEND" in m for m in msgs)


def test_inline_queue_with_memory_ratelimit_ok():
    """单进程 inline 场景用 memory 限流完全正确，不该报警。"""
    msgs = startup_warnings(_s(rate_limit_backend="memory", task_queue="inline"))
    assert not any("SC_RATE_LIMIT_BACKEND" in m for m in msgs)
