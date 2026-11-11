# E2E 验证记录 · v1.11（多模型路由与降级 + 成本对比）

> 目的：把「一个模型打天下」的调用方式改成**按任务选模型 + 失败自动降级 + 成本可对比**，
> 并且**成本数字必须可解释**：价格表写进代码，估算口径写进接口响应。

## 1. 问题

改造前：`backend/app/llm/registry.py` 只有 `openai_compat` 与 `fake` 两个 provider，
所有任务（大纲 / 章节 / 摘要 / 改写 / 图表 / PPT）都走 `settings.llm_model` 指定的**同一个**模型。
后果三条：

1. 主模型挂（限流 / 5xx / 超时）→ 任务直接失败，没有降级路径；
2. 大纲（长上下文）和小改写（短文本）用同一个昂贵模型 → 成本浪费；
3. 成本不可见：运营不知道一份 8000 字论文到底烧了多少钱。

## 2. 改后

### 2.1 路由表

新文件 `backend/app/llm/router.py`：

- `TASK_KINDS = ("outline", "chapter", "abstract", "rewrite", "diagram", "ppt", "default")`
  —— 任务类型是路由的第一维度。
- `COST_TABLE`：每模型 `{"in": 元/千 token, "out": 元/千 token}`。表里写死的是**公开报价口径**
  （deepseek-chat / deepseek-reasoner / qwen-plus / qwen-max / gpt-4o-mini / gpt-4o），
  `fake-model` 为 0（本地假 provider 不花钱）。未登记模型走兜底 `0.002 / 0.006`（按中位价保守估）。
- `_parse_routes()` 的配置来源有两条，优先级明确：
  1. `SC_LLM_ROUTES`：JSON，形如 `{"outline": ["deepseek-chat", "deepseek-reasoner"], "default": ["qwen-plus"]}`；
     **非法 JSON 只 warning 不崩**（配置写错不能让服务起不来）。
  2. 未配置 JSON 时，退回 `SC_LLM_MODEL` + `SC_LLM_FALLBACK_MODELS`（逗号分隔链），
     `default` 覆盖所有未显式指定的任务。
- `routes_for(task)` 返回该任务的候选模型列表（**顺序即优先级**）。
- `_provider_for_model(model)`：模型名等于 `fake-model` 时给 `FakeProvider`，否则 `OpenAICompatProvider(model=model)`。

### 2.2 降级

`complete_for(task, prompt, *, system, max_tokens, temperature)`：

- 按 `routes_for(task)` 顺序逐个模型试；任一模型抛异常 → `log.warning` 记下原因，**自动试下一个**；
- 全部失败 → 抛 `RuntimeError(f"任务 {task} 所有模型均失败：{', '.join(attempts)}")`，
  错误信息里带每个模型的失败原因（排查不用翻日志）。

### 2.3 成本

`estimate_cost(model, tokens_in, tokens_out) -> float`（单位：**元**）。
接口两个：

- `GET /tools/models` → `routing_table()`：当前每个任务的候选链 + 每个候选模型的单次估算成本，
  方便管理台直接渲染「这份任务可以走哪几个模型、各自多少钱」。
- `POST /tools/models/cost`（body `{task, tokens_in, tokens_out}`）→ 该任务所有候选模型的
  估算成本**按升序**返回，便于对比。

### 2.4 调用点全部改走路由

以下三处的 `get_provider()` 直连已全部删除，改为 `complete_for(task=...)`：

| 文件 | 位置 | task |
|---|---|---|
| `backend/app/tasks/local.py` | 大纲生成 | `outline` |
| `backend/app/tasks/local.py` | 章节生成 | `chapter` |
| `backend/app/tasks/local.py` | 粘贴降重改写 | `rewrite` |
| `backend/app/routers/writing.py` | 摘要生成 | `abstract` |
| `backend/app/routers/tools.py` | 改写 / PPT / 图表 | `rewrite` / `ppt` / `diagram` |

配置项新增（`backend/app/config.py`）：`llm_routes: str = ""`、`llm_fallback_models: str = ""`。

## 3. 测试

`backend/tests/test_llm_router.py` **7 passed**：

1. 路由表按任务返回不同候选链；
2. `SC_LLM_ROUTES` 非法 JSON → 不抛异常，退回默认链；
3. 降级：主模型抛异常 → 自动落到备用模型并成功返回；
4. 全部模型失败 → `RuntimeError` 且信息含各模型失败原因；
5. `estimate_cost` 精确值（按 `COST_TABLE` 口径，单位元）；
6. `GET /tools/models` 返回各任务候选链；
7. `POST /tools/models/cost` 按成本升序。

**两个踩坑（已修，写在这里防复发）**：

1. 本项目 pytest **没有** asyncio 插件的 auto 模式，异步测试必须显式标 `@pytest.mark.anyio`
   （同 `tests/test_report_push.py` 的写法）。漏标会被当成普通函数收集，测试静默不执行。
2. 降级用例除了 monkeypatch 主模型，还必须 monkeypatch `settings.llm_fallback_models="qwen-plus"`——
   否则候选链里只有主模型，测的其实是「单模型失败」，不是「降级成功」。

## 4. 版本与全套测试

- 版本 `1.10.0` → `1.11.0`（`backend/app/main.py` 的 `VERSION`、`backend/pyproject.toml`、README 徽章）。
- `openapi.yaml` 重新导出：**74 路径 / 31 schema**。
- 全量 `python3 -m pytest tests/ -q` → **207 passed, 1 skipped**（1 skip 是「本机无 TeX 引擎」的
  真编译用例，CI 装了 texlive 会真跑）。

## 5. 未验证项（如实记录）

- 未与真实厂商 API 做多模型并发压测；降级链只在**单进程内**验证。
- `SC_LLM_ROUTES` 的 JSON 校验只做「非法 JSON 不崩」，未做「模型名拼错时的提示」。
- 成本表是写死的公开报价，**不随厂商调价自动更新**；换价需改 `COST_TABLE`（写死在代码里是刻意的：
  成本数字必须可复算、可审计，不能悄悄从外部拉）。
