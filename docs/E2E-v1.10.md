# E2E 验证记录 · v1.10（图表渲染 / 前端 E2E / 数据分析 + 契约版本钉定）

> 目的：补齐 P2 三项工程/产品缺口，并把上一版 CI 的 OpenAPI 契约假红从根上钉死。

## 0. 契约版本钉定（修 v1.9 CI 的 OpenAPI 假红）

**现象**：v1.9 提交后 CI 后端 `OpenAPI 契约与代码一致` 步骤 exit 1，日志只有「openapi.yaml 与代码不一致，请重新导出」，不是测试逻辑问题。

**根因**：`pyproject.toml` 的 `fastapi>=0.115,<0.163` 在 CI 解析成 **0.162.4**，本机是 **0.115.6**；两个 FastAPI 版本对 `UploadFile` 等字段生成的 JSON Schema 形状不同（新版本多 `format: binary` 之外的差异），于是「本机导出 vs CI 导出」永远不一致。这是**依赖版本差**而不是代码 bug。

**修法**：把契约生成环境钉死——`pyproject.toml` 改 `fastapi==0.115.6`、新增 `pydantic==2.14.2`（匹配本机实际生成 `openapi.yaml` 的版本）。用全新 venv（fastapi 0.115.6 + pydantic 2.14.2）重导 `openapi.yaml` 与本机逐字节一致（`diff rc=0`），即 CI 安装同版本后必然一致。

> 教训：契约一致性门的「一致性」必须锚在**确定的生成环境**上，浮动版本上界的门是假门。

## 1. matplotlib 图表渲染（#3）

**问题**：图表只有前端 Mermaid，`grep add_picture` / `matplotlib` 在导出层均为 0——DOCX 里没有任何图。

**改后**：
- 新文件 `backend/app/export/charts.py`：`render_chart(spec, dpi=150) -> bytes`，Agg 无头后端渲染 **bar / line / pie**；自动探测系统 CJK 字体（Noto Serif/Sans CJK SC、Droid Sans Fallback…）避免方块字；`available_types()`；非法类型/长度不符/非数值均抛 `ValueError`。
- `backend/app/export/docx_builder.py`：新增 `add_chart_from_spec(doc, spec, caption=None)`（PNG 居中插入、宽 6 英寸、可选图注）；`build_thesis_docx(..., charts=None)` 在章节后追加「图表」小节逐张插入。
- `backend/app/routers/tools.py`：`GET /tools/chart/types`、`POST /tools/chart`（返回 `image/png`，非法规格 422）。
- 依赖：`pyproject.toml` 加 `matplotlib>=3.8`。

**测试** `backend/tests/test_charts.py` **6 passed**：三种图表 PNG 魔数 + 尺寸、非法类型 ValueError、长度不符 ValueError、端点返回 image/png、types 列表 + 非法 422、DOCX 内嵌 `word/media/*.png`。

## 2. 数据分析 / 问卷统计（#9）

**问题**：无任何数据分析/问卷能力。

**改后**：
- 新文件 `backend/app/analysis.py`：`describe(values)`（n/mean/median/**样本标准差 ddof=1**/min/max/q1/q3，线性插值分位数）、`pearson(xs,ys)`（方差为 0 或样本不足返回 None）、`frequency(values)`（频数 + 占比，降序）、`analyze(columns, rows, categorical)`——自动把「过半非空且全可解析为数字」的列当数值列做 describe + 两两 Pearson，其余列（或 `categorical` 显式指定）做频数分布。
- `backend/app/routers/tools.py`：`POST /tools/stats`（`columns/rows/categorical`，纯计算，行长不符或列空 422）。

**测试** `backend/tests/test_analysis.py` **7 passed**：describe 精确值（`[1,2,3,4]` mean2.5 std1.290994）、pearson ±1 与方差 0、frequency 占比、混合表 analyze、categorical 强制、行长不符 ValueError、端点 200 + 422。

## 3. 前端 E2E（#13）

**问题**：`frontend` 无任何测试，UI 改动零回归保护。

**改后**：
- 新 `frontend/playwright.config.ts`：`testDir ./tests/e2e`，`webServer` 用 `npm run start -- -p 3100`（复用构建产物），本地 `PW_CHANNEL=chrome` 走系统 Chrome 免下载浏览器，CI 走 chromium。
- 新 `frontend/tests/e2e/smoke.spec.ts` **3 条关键路径**：①首页渲染品牌/导航 + 登录表单（`手机号（11 位）` 输入 + 登录按钮）；②登录/注册切换显示短信验证码输入；③文献溯源页标题「文献检索与溯源」+ 搜索框可见且无 `pageerror`。
- `frontend/package.json` 加 `test:e2e` 脚本 + `@playwright/test` devDependency；`.gitignore` 忽略 `frontend/test-results|playwright-report|.playwright`。
- `.github/workflows/ci.yml` frontend job 追加两步：`npx playwright install --with-deps chromium` + `npx playwright test`。

**本地实测**：`/tmp/e2e-fe`（tar 副本，因工作区路径含字面反斜杠会触发 `ERR_INVALID_MODULE_SPECIFIER`）+ `npx next build` EXIT=0 → `PW_CHANNEL=chrome npx playwright test` **3 passed (2.4s)**。

## 4. 版本与全套测试

- 版本 1.9.0 → **1.10.0**（`backend/app/main.py::VERSION`、`backend/pyproject.toml`、README 徽章）。
- openapi 重导出 73 路径 / 29 schema（+ `/tools/chart`、`/tools/chart/types`、`/tools/stats`）。
- 全套 `pytest tests/` = **200 passed, 1 skipped**（+13：图表 6 + 分析 7）。
- 前端 E2E 3 条（不计入 pytest）。

## 5. 未验证项（如实记录）

- Playwright 在 **CI 真实 chromium** 上首次跑需观察（本地用系统 Chrome 验证通过；CI 下载 chromium 后同 spec 应一致）。
- 图表仅后端渲染 + 插入 DOCX 的能力，导出端点尚未从「订单数据自动生成图表」（需前端传图表规格或从章节抽取数据）。
- 数据分析为描述统计 + Pearson，未做假设检验（t 检验/方差分析）与可视化联动。
