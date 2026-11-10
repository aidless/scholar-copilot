# E2E 证据记录 · v1.4（文献三源 / 引用多源交叉 / 进度 WS / 运营日报）

执行日期：2026-11-10 ｜ 本机 uvicorn:8917 + SQLite + FakeProvider；检索与核查走真实公网

## 一、测试

```
python3 -m pytest tests/ -q → 53 passed
```

新增 `tests/test_v14_sources_ws_report.py`（6 项）：

| 用例 | 断言 |
|---|---|
| `test_litsearch_fallback_and_dedupe` | OpenAlex 抛错 → 降级 Crossref；同 DOI（大小写不同）只留 1 条 |
| `test_litsearch_openalex_polite_params` | 配置 mailto/key 后请求参数真的带上 |
| `test_citecheck_multi_source_cross_verify` | Crossref 无结果 → S2 命中 → verified 且 `evidence.source=semantic_scholar` |
| `test_citecheck_all_sources_down_raises` | 两源皆挂 → RuntimeError（路由转 502） |
| `test_job_websocket_progress_and_ownership` | 属主连 WS 收到终态快照；他人 token 连接被关闭 |
| `test_admin_report_summary` | 日报字段齐全；`days=0` → 422 |

## 二、真网络冒烟

```
GET /references/search?q=attention is all you need&limit=3
→ source=openalex n=3
  - openalex | 2017 | Attention Is All You Need | 10.48550/arxiv.1706.03762
  - openalex | 2021 | Attention Is All You Need In Speech Separation | 10.1109/icassp39728.2021.9413901
  - openalex | 2020 | Channel Attention Is All You Need for Video Frame Interpolation | 10.1609/aaai.v34i07.6693

POST /references/verify（真实 Crossref）
  - Attention Is All You Need（DOI 10.48550/arXiv.1706.03762, year 2017）→ suspicious, sim 0.905, source=crossref
    （arXiv DOI 不在 Crossref，标题命中 2017 会议版但年份字段不一致 → 降级 suspicious，符合三态设计）
  - 「一个完全不存在的编造中文标题研究」→ fake, sim 0.286

GET /admin/reports/summary?days=7 → {"window_days":7,"revenue_cents":0,"orders_new":0,"new_users":0,"jobs_by_status":{},"tokens_in":0,"tokens_out":0}
```

## 三、边界（如实声明）

- Semantic Scholar 匿名调用实测 429（限流），故放在第三顺位并在失败时记录 `semantic_scholar: ...`；
  生产建议配 `SC_SEMANTIC_SCHOLAR_API_KEY`。
- WebSocket 为服务端轮询 DB 实现（1s 粒度），多副本部署时无需粘性会话但会增加 DB 查询。
- 报表为实时查询（无定时推送），定时推送留给 v1.5。

## 四、补测：arq 队列与 WebSocket 的真实进程级联调（2026-11-10）

本机无 `redis-server` 二进制，改用 `fakeredis.TcpFakeServer`（server_type=redis，含 Lua 支持）在
`127.0.0.1:6399` 提供 **真实 TCP + Redis 协议** 端点，验证「端点 ↔ Redis ↔ 独立 worker 进程」三段链路：

```
环境：SC_TASK_QUEUE=arq SC_REDIS_URL=redis://127.0.0.1:6399/0 SC_LLM_PROVIDER=fake
进程：uvicorn app.main:app --port 8925   ＋   python -m arq app.tasks.worker.WorkerSettings

POST /writing/orders                                    → 200, price_cents=18000（6000 字本科）
POST /writing/orders/{id}/outline                       → 200 {"job_id":"295c…","status":"queued"} 0.65s
GET  /jobs/{job_id}  轮询                                → done, progress=100, error=null
GET  /writing/orders/{id}/outline                       → version=1, content_md 以「## 第一章 绪论」开头
GET  /writing/orders/{id}/chapters                      → ch1…ch5
redis KEYS arq:*                                        → ['arq:queue:health-check','arq:result:1046…','arq:result:36bd…']
```

WebSocket 走真实网络（`ws://127.0.0.1:8925/jobs/{job_id}/ws?token=`）：收到 2 帧 ——
`queued/progress=0` → `done/progress=100,result={"version":1,"chapters":5},tokens_in=27,tokens_out=102,model=fake-model`。

边界（如实）：
- Redis 端为 fakeredis TCP 假服务器（本机无 redis-server）；协议/Lua/阻塞队列行为一致，但非生产 Redis。
- worker 启动时 arq 会调 `INFO` 打日志，fakeredis 不支持 → 联调脚本里把 `log_redis_info` 置空（仅影响诊断日志）。
- 生产部署仍按 `docs/DEPLOY.md` 用真 Redis（`SC_TASK_QUEUE=arq`）。
