"""应用工厂。健康检查先行，业务路由逐版本点亮。"""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from .config import settings
from .observability import configure_logging, metrics, new_request_id, request_id_var

from . import tenancy
from .routers import (admin, auth, billing, distributor, files, formatting, jobs,
                      payments, references, review, tenant, tools, writing)

VERSION = "1.9.0"
log = logging.getLogger(__name__)
OPENAPI_PATH = "/docs"


def _route_path(request) -> str:
    """取路由模板（如 /writing/orders/{order_id}）而非原始 URL，压住指标基数。"""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or "__unmatched__"


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

        # 启动自检：把「配置看起来能跑、实际跑不通」的项在启动日志里说清楚。
        # 只警告不阻断（演示模式、自建网关无密钥等合法场景要能跑）。
        from .diagnostics import startup_warnings
        for _msg in startup_warnings(settings):
            log.warning("启动自检：%s", _msg)

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
    configure_logging(settings.log_json)

    @app.middleware("http")
    async def _observability(request, call_next):
        rid = request.headers.get("X-Request-Id") or new_request_id()
        token = request_id_var.set(rid)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            metrics.observe_request(request.method, _route_path(request), 500,
                                    time.perf_counter() - t0)
            request_id_var.reset(token)
            raise
        elapsed = time.perf_counter() - t0
        response.headers["X-Request-Id"] = rid
        metrics.observe_request(request.method, _route_path(request),
                                response.status_code, elapsed)
        request_id_var.reset(token)
        return response

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
    app.include_router(files.router)
    app.include_router(payments.router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": VERSION}

    @app.get("/metrics")
    async def prometheus_metrics():
        """Prometheus 文本暴露格式（无第三方依赖）。"""
        return PlainTextResponse(metrics.render(),
                                 media_type="text/plain; version=0.0.4; charset=utf-8")

    return app


app = create_app()
