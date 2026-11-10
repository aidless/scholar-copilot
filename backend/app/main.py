"""应用工厂。健康检查先行，业务路由逐版本点亮。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings

from . import tenancy
from .routers import (admin, auth, billing, distributor, formatting, jobs,
                      payments, references, review, tenant, tools, writing)

VERSION = "1.5.0"
OPENAPI_PATH = "/docs"


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        from .db import _engine_and_session
        import app.models  # noqa: F401——注册 metadata

        if settings.db_auto_create:
            from .db import Base

            engine, _ = _engine_and_session()
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        # 初始管理员：与建表方式解耦（alembic 建表时也要能引导）。
        # 线下交付语义：密码只从环境注入，空则不创建；已存在则跳过（幂等）。
        if settings.admin_initial_password:
            from .models import AdminUser
            from .security import hash_password
            from sqlalchemy import select, func
            async with _engine_and_session()[1]() as db:
                existing = (await db.execute(
                    select(func.count()).select_from(AdminUser))).scalar()
                if not existing:
                    db.add(AdminUser(
                        tenant_id=None, login_name=settings.admin_initial_login,
                        pass_hash=hash_password(settings.admin_initial_password),
                        role="superadmin"))
                    await db.commit()
        yield

    app = FastAPI(title="Scholar Copilot", version=VERSION,
                  description="开源学术写作 Copilot（多租户自部署）",
                  lifespan=lifespan)
    # CORS 白名单（显式配置，默认只放本地开发地址；不要用 "*" 配 cookie 认证）
    _origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if _origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["Content-Disposition"],
        )
    app.include_router(auth.router)
    app.include_router(writing.router)
    app.include_router(references.router)
    app.include_router(review.router)
    app.include_router(tenant.router)
    app.include_router(distributor.router)
    app.include_router(billing.router)
    app.include_router(admin.router)
    app.include_router(jobs.router)
    app.include_router(tools.router)
    app.include_router(formatting.router)
    app.include_router(payments.router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": VERSION}

    return app


app = create_app()
