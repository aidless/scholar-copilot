FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先装依赖（利用层缓存）
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=60s --retries=5 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2)" || exit 1

# 默认先跑迁移再起服务（幂等）；worker 容器用 docker-compose 里的 command 覆盖
# 生产：SC_DB_AUTO_CREATE=false，schema 只由 alembic 管（见 docs/DEPLOY.md）
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
