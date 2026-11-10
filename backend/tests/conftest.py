"""测试环境：必须在导入 app 前设置 env（Settings/conftest 顺序敏感）。

provider=fake（零网络）；sms_dev_mode=true（验证码 000000）；
sqlite 单文件 + 每个测试 drop_all/create_all 隔离。
"""
import asyncio
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="sc-test-")
os.environ["SC_DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP}/test.db"
os.environ["SC_LLM_PROVIDER"] = "fake"
os.environ["SC_SMS_DEV_MODE"] = "true"
os.environ["SC_JWT_SECRET"] = "test-secret-key-with-at-least-32-bytes!"
os.environ["SC_DB_AUTO_CREATE"] = "true"
os.environ["SC_PAYMENT_MODE"] = "mock"
os.environ["SC_ADMIN_INITIAL_PASSWORD"] = "t3st-Adm1n-Pw!"  # lifespan 引导初始管理员

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    from app.db import Base, _engine_and_session
    import app.models  # noqa: F401——注册 metadata

    engine, _ = _engine_and_session()

    async def _reset():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    from app.ratelimit import reset_all
    reset_all()
    asyncio.run(_reset())
    yield
    asyncio.run(_reset())
