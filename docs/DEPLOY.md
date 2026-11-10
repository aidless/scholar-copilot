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


## v1.1 新增：白标租户与分销

### 1. 迁移
```bash
cd backend && SC_DATABASE_URL=postgresql+asyncpg://... alembic upgrade head
```
新增 `tenants / tenant_configs / distributors / commissions / distributor_transfers` 五表与
`writing_orders.distributor_code` 列。

### 2. 白标租户（按域名解析）
1. 管理端建租户：`POST /admin/tenants {"name":"云笔学术","domain":"lab.example.com","plan":"pro"}`
2. 配置品牌：`PUT /admin/tenants/{id}/config {"brand_color":"#1d4ed8","logo_url":"...","support_contact":"kf@example.com"}`
3. 前端启动时拉 `GET /tenant/branding`（Host 自动识别；未绑定的域名回退 primary）。
   该接口**只返回品牌白名单字段**，渠道密钥一律不进 API。
4. 生产需在 nginx 里把各租户域名指到同一后端（`proxy_set_header Host $host;` 必须保留）。

### 3. 分销代理
1. 建代理：`POST /admin/distributors {"name":"校园代理A","phone":"138...","code":"CAMPUS01","rate_bps":500}`
   注意 `rate_bps` 是万分比（500 = 5%）。
2. 下单时用户可带 `distributor_code`；订单**支付成功**才生成 pending 佣金（同订单幂等）。
3. 结算：`POST /admin/commissions/{id}/settle` → 计入代理可提现余额。
4. 代理登录 `POST /distributor/login {code, phone}` → 查佣金 → `POST /distributor/transfers` 申请提现。
5. 平台审核：`POST /admin/distributor-transfers/{id}/pay|reject`（只登记状态，真实出款由财务线下执行）。
   所有管理动作写入 `admin_audit_log`。

### 4. PPT / 图表 / PDF
- `POST /tools/ppt {"topic","audience","pages"}` → 直接下载 .pptx（可编辑）。
- `POST /tools/diagram {"description","kind":"flowchart|sequence|architecture"}` → 返回 Mermaid 源码。
- 导出 PDF 依赖宿主机 LibreOffice：`apt install libreoffice-writer`；缺失时自动 502 并提示改用 docx。

### 5. 常见问题
- **branding 返回 primary**：Host 头没传或域名未在 tenants 表登记（检查反向代理是否保留 Host）。
- **代理提现 400**：可提现 = 已结算佣金 − 已申请/已付，先 settle 佣金。
- **PDF 502**：`which soffice` 为空，装 LibreOffice；或改用 `format=docx`。


## v1.2 新增：短信验证码、微信扫码登录、任务队列

### 1. 迁移
```bash
cd backend && alembic upgrade head   # → ff5854424543
```
新增 `sms_codes`、`wechat_scenes` 两表。

### 2. 短信验证码
| 变量 | 说明 |
|---|---|
| `SC_SMS_PROVIDER` | `dev`（只打日志，不发真短信）或 `http` |
| `SC_SMS_API_URL` | http 驱动的网关地址，POST `{phone, code, scene}` |
| `SC_SMS_API_TOKEN` | 网关 Bearer token（可空） |
| `SC_SMS_DEV_MODE` | true 时接受万能码 `000000` 并回显 `dev_code`，**生产必须设 false** |
| `SC_SMS_CODE_TTL_SECONDS` | 验证码有效期，默认 300 |

发送：`POST /auth/sms/send {"phone","scene":"register|login"}`——无论号码是否注册，响应一致。
校验：`POST /auth/register` 的 `check_code`；一次性消费、5 次错误即失效。

### 3. 微信扫码登录
- 未配置 `SC_WECHAT_APP_ID`：dev 模式下 `POST /auth/wechat/qrcode` 返回 `mode=dev` 与 `dev://` 场景，
  用 `POST /auth/wechat/mock-approve {scene, phone}` 模拟扫码确认，再 `GET /auth/wechat/poll?scene=` 取 token。
- 配置后返回真实 `open.weixin.qq.com` 扫码链接；回调确认需在网关侧把 scene → confirmed（`wechat_scenes` 表）。
- **生产必须设 `SC_SMS_DEV_MODE=false`，否则 mock-approve 会 403、万能码失效。**

### 4. 任务队列（多实例部署）
```bash
# .env
SC_TASK_QUEUE=arq
SC_REDIS_URL=redis://redis:6379/0
# 独立 worker 进程（可多副本）
arq app.tasks.worker.WorkerSettings
```
端点据此把生成任务投递给 worker（返回 job_id，前端照旧轮询 `GET /jobs/{id}`）。
默认 `inline` 单机即可用，无需 Redis。
> 说明：本仓库已提供 arq 通道实现与投递单测；本机无 Redis，未做进程级联调（部署环境验证）。
