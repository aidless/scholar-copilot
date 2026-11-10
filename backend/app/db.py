"""异步 SQLAlchemy 会话。所有模型必须带 tenant_id/owner_id 列（见 init.sql 注释）。

引擎惰性创建：导入本模块不要求 PG 驱动可用（健康检查/纯单测不依赖数据库）。
"""
from functools import lru_cache

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


@lru_cache(maxsize=1)
def _engine_and_session():
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    _, SessionLocal = _engine_and_session()
    async with SessionLocal() as session:
        yield session
