# v1.0 端到端验证记录（2026-11-10）

范围：P0 加固全部项 + 前端可用 UI。以下每条都有实跑证据。

## 1. 后端测试（34 passed）

```
cd backend && python3 -m pytest tests/ -q
→ 34 passed, 1 warning in 32.98s
```

新增 4 项加固测试（tests/test_hardening.py）：

| 用例 | 断言 | 结果 |
|---|---|---|
| 登录限流 | 3 次/分上限下：401,401,401,429；429 带 `Retry-After`；detail 含「频繁」 | PASS |
| 检索限流 | 2 次/分：200,200,429 | PASS |
| CORS 白名单 | `localhost:3000` 有 ACAO；`evil.example` 无 ACAO；OPTIONS 预检 200 | PASS |
| prompt 注入逃逸 | `wrap_untrusted` 输出中 `CLOSE` 恰 1 个、开哨兵恰 1 个、原文保留 | PASS（首跑红：GUARD 含哨兵 + 分离 `>>>` 未中和 → 修 safety.py 后绿） |

## 2. Alembic 迁移（空库可落地）

```
SC_DATABASE_URL="sqlite+aiosqlite:////tmp/alembic-t.db" python3 -m alembic upgrade head
→ 成功；alembic current → 64bfd6724d4e (head)
```
迁移脚本：`backend/migrations/versions/64bfd6724d4e_initial_schema_v0_5_0.py`（10 张表）。

## 3. Docker 镜像（后端真实构建 + 容器内冒烟）

```
DOCKER_BUILDKIT=0 docker build -t scholar-copilot-backend:test ./backend
→ Successfully built 6968f1405ef5
docker run ... scholar-copilot-backend:test
GET /health → {"status":"ok","version":"1.0.0"}
POST /auth/register（dev 验证码 000000）→ 200 + access_token
```

## 4. 前端构建（6 路由，typecheck 通过）

```
npm install → 46 packages
next build →
┌ ○ /            ├ ○ /admin      ├ ○ /references
├ ○ /review      └ ○ /workbench  (+ /_not-found)
First Load JS shared 103 kB
```
> 环境注：工作区路径含反斜杠（`F:\deepseek`），Node ESM 拒绝带编码反斜杠的模块路径 →
> 构建在 `/tmp/scfe`（同一份源码 tar 拷贝）完成。CI（ubuntu-latest）无此问题。

## 5. docker compose 配置校验

```
docker compose config → rc=0（services: postgres/redis/backend/frontend）
```

## 6. 已知未验证项（如实记录）

- **前端 Docker 镜像未构建**：registry-1.docker.io 在本机不可达（pull `node:20-alpine` 超时），
  `python:3.12-slim` 因本地已有缓存才得以构建后端的。Dockerfile 已写好、CI 会在 GitHub runner 上验证。
- **arq worker 未启用**：任务仍是进程内 `asyncio.create_task`（v1.1 计划）。
- 限流是进程内（单副本有效），多副本需接 Redis（v1.1）。
