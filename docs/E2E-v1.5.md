# E2E 证据：v1.5 运营闭环（限流 Redis 后端 + 日报定时推送）

日期：2026-11-10　版本：1.5.0　测试：**69 passed**

## 1. 限流 Redis 共享计数

### 问题（实测）
进程内滑动窗口（`app/ratelimit.py` 原实现）在 `--workers 2` 或多副本部署下
**真实配额 = 配置值 × 实例数**，撞库/短信轰炸防护形同虚设。

### 改法
- `app/ratelimit.py` 增 redis 后端：sorted set 滑动窗口，一次 pipeline 完成
  「清理过期 → 计数 → 判断 → 写入 → 续期」。
- `SC_RATE_LIMIT_BACKEND=memory|redis`；compose 默认 `redis`（五容器共享同一 Redis）。
- Redis 不可用 → **降级进程内并 `log.warning`**，不抛 500（限流是防护层，不是正确性层；
  但降级必须留痕，不能静默）。

### 抓出的实现 bug
第一版用 `f"{now_ms}-{id(pipe)}"` 作 zset member。同一毫秒内两次请求若 `id()` 相同
（CPython 里对象地址会被复用），`zadd` 会**覆盖**而非累加 → 计数少算、限流不生效。
改 `uuid4().hex[:8]` 后缀。RED 反证：改回同毫秒 member → `test_redis_backend_shares_quota_across_processes` 立刻变红。

### 实测（compose 全栈，backend 18000 / redis 16379）
```
连续 25 次错误登录 → codes: [401 ×20, 429 ×5]
首次 429 出现在第 21 次（limit=20，符合「窗口内第 limit+1 次拒绝」）
Retry-After: 60
redis-cli KEYS 'rl:*' → rl:login:172.24.0.1
```

### 测试（tests/test_ratelimit_redis.py，4 项，fakeredis 免真 Redis）
| 用例 | 断言 |
|---|---|
| 共享配额 | limit=3 时第 4 次抛 429 且带 Retry-After |
| 键隔离 | 不同 IP / 不同路由互不影响 |
| 窗口过期 | 时间跨过窗口后重新放行 |
| Redis 挂掉降级 | `pipeline()` 抛错时仍限流，且不 500 |

## 2. 运营日报定时推送

### 设计
- 计算口径抽到 `app/reports.py::summary`，`GET /admin/reports/summary` 与定时推送**共用**
  （两处各写一遍 SQL 迟早漂移；日报与管理台数字对不上是最难查的运维问题）。
- `app/tasks/report.py::push_daily_report`：arq cron 入口，默认 `SC_REPORT_PUSH_ENABLED=false`
  且 webhook 为空时**不发任何请求**（自部署用户不该被莫名打外部接口）。
- webhook 载荷同时给 `msgtype/text`（企业微信/飞书/Slack 机器人直接可用）与 `data`（结构化）。
- 推送失败（HTTP 500 / 连不上）返回 `{"pushed": false, ...}`，不抛异常——否则 arq cron 反复刷错误日志。

### 抓出的实现 bug
`format_text` 里写成了 `\\n`（字面反斜杠 n），IM 里正文会挤成一行。
已修，并在测试里加断言 `"\\n" not in content and content.count("\n") == 3`。
RED 反证：把换行改回字面 `\n` → 该用例变红。

### 实测（本地起 HTTP webhook 接收器，真跑一次）
```
push result: {"pushed": true, "status_code": 200}
webhook 收到条数: 1
msgtype: text
data: {"window_days":1,"revenue_cents":50000,"orders_new":2,"new_users":2,
       "jobs_by_status":{"done":12},"tokens_in":2516,"tokens_out":954}
text:
Scholar Copilot 运营日报（近 1 天）
收入 ¥500.00 ｜ 新订单 2 ｜ 新用户 2
生成任务 done=12
Token 用量 in=2516 out=954
```

### 测试（tests/test_report_push.py，6 项）
| 用例 | 断言 |
|---|---|
| 关闭时不发 | 返回 `{"pushed":false,"reason":"disabled"}`，`sent == []` |
| 无 webhook 不发 | `reason == "no_webhook_url"`，`sent == []` |
| 口径同源 | 推送 `data` 的 revenue/orders/new_users/tokens 与 `reports.summary` 逐项相等 |
| 换行正确 | 正文含真换行、不含字面 `\n` |
| webhook 500 | `pushed=false, status_code=500`，不抛 |
| 网络异常 | `pushed=false`，`error` 含原因 |
| cron 注册 | 关闭时 `_cron_jobs()==[]`；开启时 1 个 `daily_report`，hour 跟随配置 |

## 3. 未验证项（如实）
- 日报 cron 的**真实到点触发**未跑（需等一个整点或临时改 `report_push_hour` + 真 arq worker 常驻）；
  已验证的是「cron 注册正确 + 任务体真跑成功」两段，中间的时间调度由 arq 自身保证。
- 限流 Redis 后端在 `--workers 2` 的多进程场景下未单独压测；共享语义已由 fakeredis 的
  独立客户端实例覆盖（同一 Redis、不同调用栈）。
