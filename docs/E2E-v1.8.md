# E2E 验证记录 · v1.8（假功能补真 P0 + 可观测性）

> 目的：把清单里「看起来有、实际是空壳/未接线」的四处（review 审计、引用格式导出、可观测性、前端排版档案）补成真的，并留下可复算证据。

## 1. `review/orders/{id}/audit` 从 501 空壳变真审计引擎

**改前**：`backend/app/routers/review.py` 全文只有一句 `raise HTTPException(501, "v0.4 实现：移植 review-workflow 规则")`。

**改后**：
- 新文件 `backend/app/audit.py`——纯函数规则引擎，`audit(chapters, refs, cliche_phrases=None) -> {verdict, summary, issues, disclaimer}`，零 IO 可单测。
- 七类规则（每条 issue 带 `code/level/ref/evidence`）：
  | code | level | 触发 |
  |---|---|---|
  | `ref_invalid` | fail | 文献 `verify_state` ∈ {fake, suspicious}（含 `evidence.score`） |
  | `cite_index_missing` | fail | 正文出现 `[N]` 但 N > 文献条数 |
  | `ref_unverified` | warn | 文献 `verify_state` 为 unknown/unverified |
  | `ref_uncited` | warn | 文献从未在正文被 `[N]` 引用 |
  | `number_without_citation` | warn | 含 `%`/`p值`/`n=` 的句子没有引用标号 |
  | `ai_level_mismatch` | warn | 章节标 `ai_level=C`（纯 AI）却含 ≥3 个 AI 套话 |
  | `chapter_empty` | warn | 章节去空白后为空 |
  | `word_count_drift` | warn | 声明字数与实际字数偏离 > ±20% |
- `verdict`：有 fail → `fail`；只有 warn → `warn`；否则 `pass`。
- 路由 `POST /review/orders/{order_id}/audit?only=ref_invalid,cite_index_missing`（`only=` 按类过滤）、`GET /review/orders/{order_id}/audit/summary`（只出 verdict+计数，前端可做红绿灯），两条均先走 `_get_owned_order` 属主校验（非属主 404）。

**测试** `backend/tests/test_review_audit.py` **12 passed**：逐规则命中 + `only=` 过滤 + verdict 三态 + 属主 404 + summary 形状。

## 2. 引用格式导出（真实规则渲染）

**改前**：`grep -rn "bibtex\|gb7714\|ieee"` = 0，只有「核查」没有「按格式导出」。

**改后**：新文件 `backend/app/export/citation.py`——`STYLES` + `render(items, style) -> (text, media, ext)`：
- `gb7714`（GB/T 7714-2015）：≤3 作者全列，>3 用「前 3, 等」；`[序号] 作者. 题名[J]. 刊名, 年, 卷(期): 页.`
- `apa`：英文名 `Last, F. M.`、CJK 名原样，作者用 `, ` 连接（不用 `&`），`(年). 题名. 刊名.`
- `ieee`：名缩写（`A. B. Last`），作者间 `and`，`[序号] 作者, "题名," 刊名, 年.`
- `bibtex`：`@article{ref{i}_Firstword{year}, ...}`，`url` 型文献降级 `@misc`
- `ris`：`TY/TI/AU/PY/DO/UR/ER` 标签块
- 路由 `GET /references/styles`（列五种 key）、`GET /references/orders/{order_id}/export?style=`——非属主 404 / 无文献 409 / 未知 style 422 / `Content-Disposition` 带 `.txt|.bib|.ris`。

**测试** `backend/tests/test_citation_export.py` **11 passed**：五种风格逐风格断言关键片段 + 未知 style 422 + 空文献 409 + 属主 404 + 后缀/媒体类型。

## 3. 可观测性（Prometheus 指标 / 请求追踪 / 结构化日志）

**改前**：`grep -rn "prometheus\|opentelemetry\|sentry" backend/` = 0。线上出问题只能翻 uvicorn 文本日志。

**改后**：新文件 `backend/app/observability.py`（零第三方依赖，手写 Prometheus 文本暴露）：
- `Metrics.observe_request/observe_tokens/set_job_status/render`——指标 `http_requests_total{method,path,status}`、`http_request_duration_seconds_{sum,count}{method,path}`、`llm_tokens_total{kind,direction}`、`generation_jobs_by_status{status}`；标签做 `\ " \n` 转义防注入。
- `main.py` 的 `@app.middleware("http") _observability`：透传/生成 `X-Request-Id` 写回响应头 + `request_id_var` contextvar（日志可带）+ 记时记数；**path 用路由模板**（`request.scope["route"].path`，未匹配落 `__unmatched__`）压住基数，避免 `/orders/{uuid}` 炸出百万序列。
- `GET /metrics` 返回 `text/plain; version=0.0.4`。
- `SC_LOG_JSON=true` → 根 logger 换 `JsonLogFormatter`（`ts/level/logger/msg/request_id/exc` 一行一 JSON）；`tasks/local.py` job done 后把 `tokens_in/out` 计入 `llm_tokens_total`。

**测试** `backend/tests/test_observability.py` **6 passed**：暴露格式 + 标签转义 + `/metrics` 端点计数 + 路由模板非原始路径 + `X-Request-Id` 透传/回写 + JSON 日志格式合法 + `configure_logging` 开关。

## 4. 前端写作台接入排版档案 + 多格式导出

**改前**：`frontend/app/workbench/page.tsx` 导出按钮写死 `POST .../export`（无 `profile`/`format`，永远默认版式 DOCX），后端已支持的 `GET /formatting/profiles` 前端没人调。

**改后**：写作台加载时拉 `/formatting/profiles`；导出区变成「格式档案下拉（默认版式 + 各学校模板）+ 格式下拉（DOCX/PDF/LaTeX 源码/LaTeX→PDF）+ 导出」，导出时拼 `?profile=&format=`，按格式映射下载后缀（tex→.tex，其余 docx/pdf）。后端 `apply_format_profile` 未知 profile 抛 `KeyError` → 422 已有测试覆盖。

**构建验证**：`npx next build` EXIT=0，8 路由；`/workbench` 4.39 kB / First Load JS 107 kB。

## 5. 未验证 / 已知边界
- 审计引擎的规则是**启发式**（正则 + 计数），不是语义级；`disclaimer` 字段明确声明「不替代人工终审、不替代专业查重」。
- 引用格式对**英文姓名解析**（`First Last` vs `Last, First`）用启发式判断，少见命名可能误判，导出内容可人工再校。
- `/metrics` 为进程内指标，多 worker/多实例下需各自 scrape 或接 Prometheus 聚合（未做 push gateway）。
- Sentry 未接（保留为可选扩展，避免强依赖）；结构化日志落 stdout，采集由部署侧负责。
