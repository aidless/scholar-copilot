# E2E 证据记录 · v1.2（认证强化 / 微信扫码 / 任务队列）

执行日期：2026-11-10 ｜ 本机 uvicorn + SQLite，LLM=FakeProvider（认证/队列不依赖模型）

## 一、测试

```
python3 -m pytest tests/ -q → 45 passed (47.31s)
```

新增 `tests/test_auth_sms_wechat_queue.py`（5 项）：

| 用例 | 断言 |
|---|---|
| `test_sms_send_and_register_with_real_code` | dev 回显 6 位码；错误码 400；正确码注册 200；码一次性（复用 400）；/auth/me 200 |
| `test_sms_send_does_not_leak_registration_state` | 已注册号与未注册号响应**字段集合与 expires_in 完全一致**（无 oracle） |
| `test_wechat_mock_login_flow` | qrcode→pending→mock-approve→confirmed→token 可用 |
| `test_wechat_mock_approve_forbidden_outside_dev` | `SC_SMS_DEV_MODE=false` 时 mock-approve 403 |
| `test_queue_arq_path_enqueues_without_running` | `SC_TASK_QUEUE=arq` 时端点只 `enqueue_job("run_job_task", job_id)`，job 保持 queued（不内联执行） |

## 二、迁移

```
alembic upgrade head → ff5854424543 (head)
新增 sms_codes / wechat_scenes 两表
```

## 三、arq worker 可加载

```
pip install arq → arq 0.28.0
python -c "from app.tasks.worker import WorkerSettings" → functions=['run_job_task','outline_task','chapter_task']
```

## 四、边界（如实声明）

- 本机无 Redis，arq 只做到「投递语义 + worker 可加载」验证，未做进程级端到端联调。
- 微信扫码生产回调（用户真正扫码后由微信服务器推事件）需在网关侧落地，本仓库提供 scene 状态机与轮询端点。
- 短信真实下发需自备网关（`SC_SMS_PROVIDER=http` + URL/Token）。
