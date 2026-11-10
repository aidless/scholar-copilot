# 部署指南（v1.0）

本仓库三种跑法：**Docker Compose 一键起**（推荐演示/小规模）、**本地开发**、**生产部署**。

---

## 1. Docker Compose（一键）

```bash
cp .env.example .env        # 按需改 SC_JWT_SECRET / SC_LLM_* / SC_ADMIN_INITIAL_PASSWORD
docker compose up -d --build
# 前端 http://localhost:3000   后端 http://localhost:8000/health
```

compose 起来的东西：

| 服务 | 端口 | 说明 |
|---|---|---|
| postgres | 5432 | 首次启动执行 `deploy/init.sql`；数据在 `pgdata` 卷 |
| redis | 6379 | 预留给 v1.x 的 arq 任务队列 |
| backend | 8000 | FastAPI，`SC_DB_AUTO_CREATE=true` 演示模式启动建表 |
| frontend | 3000 | Next.js 15（`NEXT_PUBLIC_API_BASE` 指向后端） |

> 演示模式用 `SC_DB_AUTO_CREATE=true` 免去迁移；**生产必须关掉并跑 alembic**（见 §3）。

## 2. 本地开发

```bash
# 后端
cd backend
pip install -e ".[dev]"          # 或 pip install --user --break-system-packages -e ".[dev]"
export SC_DATABASE_URL="sqlite+aiosqlite:///./dev.db"   # 零外部依赖起步
export SC_LLM_PROVIDER=fake      # 或 openai_compat + SC_LLM_BASE_URL/SC_LLM_API_KEY/SC_LLM_MODEL
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm install && npm run dev       # http://localhost:3000
```

测试：`cd backend && python -m pytest tests/ -q`（fake provider + sqlite 临时库，零网络零外部服务）。

> 提示：若工作区路径含反斜杠（如 `F:\...`），Node 的 ESM 解析会拒绝带编码反斜杠的路径，
> `next build` 需要把 frontend 目录放到普通路径下构建（或换 Linux/macOS 路径）。

## 3. 生产部署

1. **数据库迁移**（不要用自动建表）：
   ```bash
   export SC_DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/scholar"
   alembic upgrade head
   ```
2. **必改的环境变量**：
   - `SC_JWT_SECRET`：强随机（≥32 字节），不要用默认值；
   - `SC_SMS_HMAC_KEY`：短信签名密钥（配合真实短信网关）；
   - `SC_LLM_BASE_URL/SC_LLM_API_KEY/SC_LLM_MODEL`：接入任一 OpenAI 兼容端点；
   - `SC_CORS_ORIGINS`：只写前端域名，勿用 `*`；
   - `SC_PAYMENT_MODE=manual`：关闭 mock 自动确认，改由管理员核对回执后确认；
   - `SC_ADMIN_INITIAL_PASSWORD`：首次启动引导 superadmin（之后请改密码并置空该变量）。
3. **反向代理**：nginx/caddy 终止 TLS，`/api/*` 转 8000、其余转 3000；`X-Forwarded-For` 需透传
   （限流按 IP 计，取 `request.client.host`；上代理后请确认取到真实 IP）。
4. **限流**：进程内滑动窗口，多副本部署时每副本独立计数；如需全局限流，v1.x 接 Redis。
5. **备份**：`pgdata` 卷或 `pg_dump` 定时备份；`quota_ledger` / `admin_audit_log` 均为 append-only，
   不要删行（对账与审计依赖它们）。
6. **健康检查**：`GET /health` 返回版本号；Dockerfile 已内置 HEALTHCHECK。

## 4. 常见问题

- **登录 429**：触发登录限流（默认 20 次/分钟/IP），等 `Retry-After` 秒数即可，或调 `SC_RATE_LIMIT_LOGIN_PER_MINUTE`。
- **正文生成 402**：订单未支付——先 `POST /payments/orders/{id}` 再 `confirm`（大纲阶段免费）。
- **检索 502**：OpenAlex/Crossref 均不可达（含限流）；换关键词重试，或稍后再试。
- **导出报「还有 N 个章节未完成」**：先把所有章节生成/保存到 done 状态。
