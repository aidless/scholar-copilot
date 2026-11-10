# E2E 证据：v1.6 检索四源 + 任务进度 WebSocket

日期：2026-11-10　版本：1.6.0　测试：**83 passed**

## 1. 文献源扩到四源（新增 PubMed）

### 为什么加 PubMed
OpenAlex/Crossref/S2 覆盖 preprint 与 DOI 注册库，但医学与生命科学的大量文献
只在 PubMed 有（尤其临床期刊）。少这一源，护理/医学类毕设的文献推荐直接缺一条腿。

### 实现（`app/litsearch.py`）
- 两步检索：`esearch.fcgi` 拿 PMID 列表 → `esummary.fcgi` 拿元数据。
  不走 `efetch` 的 XML：字段够用且省掉 XML 解析。
- `_norm_pubmed` 两个易错点已单测钉住：
  - DOI 不在顶层，要从 `articleids` 里挑 `idtype == "doi"` 的那条；
  - 年份要从 `pubdate`（形如 `"2021 Mar 15"`）前四位取，且可能只有 `"2019"`。
  - 无 DOI 时回落到 `https://pubmed.ncbi.nlm.nih.gov/{uid}/`。
- 源链改为 `OpenAlex → Crossref → Semantic Scholar → PubMed`，逐个降级；
  任一本源非空即停（多源是「这个挂了还有别的」，不是混排）。
- 开关：`SC_PUBMED_ENABLED`（默认 true）。有些部署只想要 DOI 库，关掉即可。
- 凭据：`SC_PUBMED_API_KEY`（3 req/s → 10 req/s）、`SC_PUBMED_EMAIL`。

### 实测（真网络）
```
_pubmed("attention is all you need", 5) → 返回 5 条
 - "You don't know what it's like until you live with it:" A qualitative … | 2026 | 10.1093/jsxmed/qdag335 | The journal of sexual medicine
 - AMEE guide to resistance in medical education: AMEE Guide No. 197       | 2026 | 10.1080/0142159X.2026.2754843 | Medical teacher
 - Attention when you need                                                | 2026 | (no doi) | ArXiv
```
（注：PubMed 对自然语言查询按全文相关性排序，结果不必是那篇 Transformer 论文；
这条记录的是「源通、字段解析对」，不是「检索质量」，后者由上层 query 构造决定。）

### 测试（`tests/test_v14_sources_ws_report.py` 新增 5 项）
| 用例 | 断言 |
|---|---|
| DOI/年份提取 | `10.1000/xyz` 而非 pubmed id；`2021 Mar 15` → 2021；标题去句末点 |
| 无 DOI 回落 | url = `pubmed.ncbi.nlm.nih.gov/999/` |
| 空标题跳过 | 返回 None |
| 凭据透传 | api_key/email/db/retmode 都在 esearch 参数里；无结果不再打 esummary |
| 关闭即不调用 | `SC_PUBMED_ENABLED=false` 时四源全挂也不碰 PubMed |

RED 反证：把 `if settings.pubmed_enabled:` 改成 `if True:` → 「关闭即不调用」变红。

## 2. 写作台任务进度接 WebSocket

### 问题
生成一章 30~60 秒，前端原来用 `?wait=true` 同步阻塞（浏览器转圈、网关超时风险），
或者要 2 秒轮询几十次。后端 v1.4 已有 `/jobs/{id}/ws`，前端没接。

### 实现（`frontend/lib/jobProgress.ts`）
- `useJobProgress(jobId)` → `{ state, transport }`。
- 连 `ws://…/jobs/{id}/ws?token=`；终态（done/failed）后不再重连。
- **降级**：WS 建不起来（反向代理没配 `Upgrade`、浏览器不支持）或非终态断开 →
  自动退回 2 秒轮询 `/jobs/{id}`。`transport` 暴露给 UI，用户能看到当前是
  「实时推送」还是「轮询降级」——传输层出问题时不会静默变慢。
- 组件卸载清理定时器与连接（避免 React 严格模式下的双连）。

### 写作台改动（`app/workbench/page.tsx`）
大纲 / 逐章生成 / 降重改写三处从 `?wait=true` 改为「提交拿 job_id + 订阅进度」，
进度条显示 `kind · status`、百分比与传输方式；终态回调刷新章节与订单，失败显示后端 error。

### 实测
后端 uvicorn 8919 + fake provider：
```
order price_cents = 18000
outline job: 0e7f26e9e300439b94a7eee911938250 queued
frame: done 100 {'version': 1, 'chapters': 5}
总帧数: 1
```
（fake provider 秒级完成，只收到终态帧；真实模型的中间帧在 v1.4 已验过 queued/progress=0 → done/100。）

前端构建：8 路由通过，`/workbench` 4.03 kB（接入 hook 后 +1.7 kB），
First Load JS 107 kB。

## 3. 引用核查接 PubMed 交叉（第三源）

### 改动（`app/citecheck.py`）
- 新增 `_pubmed_title`：与 litsearch 同款两步（esearch → esummary），DOI 从 `articleids` 挑。
- 标题匹配的补查链从「Crossref → S2」扩到「Crossref → S2 → PubMed」，
  且**任一本源达到 verified 阈值（0.85）就停**——多源是为了「这个查不到还有别的」，
  不是为了把三个源都打一遍（每多打一源都是延迟与配额）。
- `SC_PUBMED_ENABLED=false` 时 PubMed 不进补查链。

### 实测（真网络）
```
_pubmed_title("Effect of metformin on type 2 diabetes") → 3 条
 - Tissue-resolved transcriptomic and proteomic profiling … | 2026 | 10.3389/fendo.2026.1954533
 - Clinical pharmacology of antidiabetic drugs: an update   | 2026 | 10.1007/s00228-026-04219-z
verify_citation("Effect of metformin on type 2 diabetes") → suspicious 0.703 crossref
verify_citation("这是一个完全编造的中文标题量子计算与诗意") → fake 0.2 crossref
```
（S2 侧本轮命中匿名 429，正好演示了降级：日志记 warning，链路继续走到下一源。）

### 测试（新增 4 项）
| 用例 | 断言 |
|---|---|
| Crossref 空 + S2 挂 → PubMed 命中 | state=verified，`evidence.source == "pubmed"`，matched_doi 正确 |
| 首源已 verified | S2 与 PubMed 调用计数均为 0（不浪费配额） |
| 关闭 PubMed | 全空时 state=fake 且 PubMed 未被调用 |
| esummary 解析 | 两次请求（esearch+esummary）、DOI 取 doi 而非 pubmed id、年份 2018、标题去句末点 |

RED 反证：删掉 `if best_sim >= _TITLE_MATCH: break` → 「首源已 verified 不再补查」变红。

## 4. compose worker 健康检查修复 + arq 队列在 compose 栈上实测

### 问题（实测发现）
`docker ps` 里 `sce2e-worker-1` 一直是 **unhealthy**（FailingStreak=64），
但 worker 实际在正常消费任务——**假警报**。根因：`backend/Dockerfile` 里的
`HEALTHCHECK` 探的是 `http://127.0.0.1:8000/health`，而 worker 容器用 compose 的
`command` 覆盖成 `python -m arq ...`，**根本不监听 HTTP 端口**。

假警报的危害不只是难看：`depends_on: condition: service_healthy` 的下游服务
（例如以后加的前端 SSR 或定时备份）会被永久卡住不启动。

### 修法（两轮）
1. 第一版用 `pgrep -f 'arq app.tasks.worker.WorkerSettings'` → 实测
   `/bin/sh: 1: pgrep: not found`：`python:3.12-slim` 不带 procps（`ps` 也没有）。
2. 改为纯 python 读 `/proc/*/cmdline` 自查，零额外依赖：
   ```yaml
   healthcheck:
     test: ["CMD-SHELL", "python -c \"import glob,sys; sys.exit(0 if any(b'arq' in open(f,'rb').read() for f in glob.glob('/proc/[0-9]*/cmdline')) else 1)\""]
     interval: 15s
     timeout: 3s
     start_period: 20s
     retries: 3
   ```

### 验证
```
docker inspect sce2e-worker-1 --format '{{.State.Health.Status}} FailingStreak={{.State.Health.FailingStreak}}'
→ healthy FailingStreak=0
```

### arq 队列在 compose 栈上真跑（不只是 fakeredis）
```
POST /writing/orders/{id}/outline  → job e6bc2c2a97854874813dd1b876cfa128 queued
轮询 → done 100 {'version': 1, 'chapters': 5}  model=fake-model
chapters: 5

docker logs sce2e-worker-1:
14:14:34:   0.49s → 9f76dcb3…:run_job_task('e6bc2c2a97854874813dd1b876cfa128')
14:14:35:   0.92s ← 9f76dcb3…:run_job_task ● {'job_id': '…', 'worker': '?'}

docker exec sce2e-redis-1 redis-cli KEYS 'arq:*'
→ arq:result:…, arq:queue:health-check
```
即：**backend 只入队、独立 worker 进程消费**，不是 inline 执行。

### 未验证
- worker 镜像仍是 v1.4 时的构建（日志显示 `3 functions`，未含 v1.5 的
  `push_report_task`）；重新 `docker compose build` 后才有 4 个函数与日报 cron。
  本轮验证的是队列通道本身，不是最新镜像内容。


## 5. API 契约改为代码导出 + 一致性门

### 问题
`openapi.yaml` 是 v0.1 手写骨架（18 个端点，带 `x-origin` 与原产品对照），
而代码已长到 **53 个端点**。文档与实现静默脱节——外部按契约对接必然踩空，
而且没人会发现（没有任何检查）。

### 改法
- 新增 `backend/scripts/export_openapi.py`：从 `create_app().openapi()` 导出，
  补 `info`（版本跟 `app.main.VERSION`）、`servers`、`securitySchemes`（Bearer JWT），
  并按匿名端点白名单（`/health`、`/auth/login|register|sms|wechat`、`/tenant/branding`、
  `/billing/quote`、`/formatting/profiles`、`/references/search|verify`、`/admin/login`、
  `/distributor/login`）给其余端点打 `security`。
  > 为什么要手工补 `securitySchemes`：路由用 `Header(default="")` 依赖解析 Bearer，
  > 而不是 FastAPI 的 `Security()`，所以框架不会自动生成 securitySchemes——
  > 不补的话 SDK 生成器不会带 `Authorization` 头。
- 支持 `--check`（只校验不写）与 `--out`（写别处，供测试比对）。
- `backend/tests/test_openapi_sync.py` 5 项：文件存在 / 路径集合与代码一致 /
  版本与 `VERSION` 一致 / 有 bearer securityScheme / **重跑导出脚本结果与仓库文件逐字段相同**。
  最后一条比「路径集合相同」更严：能抓出描述文字、字段定义被改却没提交。
- CI 加独立步骤 `python -m scripts.export_openapi --check`（在 pytest 之前挡）。

### 实测
```
python -m scripts.export_openapi
→ 已写入 openapi.yaml（53 个路径，24 个 schema）
python -m scripts.export_openapi --check
→ 已是最新（53 个路径） rc=0
pytest tests/test_openapi_sync.py -q  → 5 passed
```

### RED 反证（两条都验过）
| 注入 | 结果 |
|---|---|
| 从文档里删掉 `/tools/ppt` | `test_openapi_yaml_matches_code` 红 |
| 把 `info.version` 改成 `0.0.9` | `test_openapi_yaml_version_matches_app` 红 |
恢复后 5 passed。

### 取舍说明
旧文件的 `x-origin`（与原产品端点对照）在代码导出的契约里没有——那份对照的价值
已经沉在 README 的「与逆向原产品的差异」表和 `blx-recon` 报告里，契约文件只留事实。


## 6. 启动自检（延迟暴露的配置错误前置）

### 问题
clone 下来 `docker compose up -d`，`SC_LLM_API_KEY` 没填时：服务能起、页面能开、
下单也成，**直到第一次生成才 401**，报的还是上游错误——用户会以为是代码坏了。
同类问题还有：`SC_SMS_DEV_MODE=true` 带到生产（任意手机号 000000 就能注册）、
`SC_PAYMENT_MODE=mock`（支付不校验渠道）、JWT 密钥还是 `change-me`、
`SC_DB_AUTO_CREATE=true` + Postgres（create_all 与 alembic 双真相源）、
`SC_RATE_LIMIT_BACKEND=memory` + arq 多进程（配额按容器数放大，v1.5 真踩过）。

### 改法
`backend/app/diagnostics.py::startup_warnings(settings) -> list[str]`，纯函数（便于测试），
`main.py` 的 lifespan 里逐条 `log.warning("启动自检：%s", msg)`。**只警告不阻断**——
演示模式、自建网关无密钥都是合法场景。

覆盖 9 类：fake provider / 缺 LLM 密钥（含占位符 `sk-xxx`、`changeme`、`todo` 等）/
SMS dev 模式 / SMS provider=dev / mock 支付 / 无初始管理员 / 默认 JWT 密钥 /
Postgres + auto_create / memory 限流 + arq 队列。

### 实现 bug（已修，测试抓到）
`_PLACEHOLDER_KEYS` 里写了大写 `"TODO"`，但比对前做了 `.lower()` → **永远匹配不上**。
`test_placeholder_llm_key_warns` 用 `("sk-xxx", "changeme", "TODO", "   ")` 四个值跑
直接红在 `TODO`。改为全小写 `{"", "sk-xxx", "your-api-key", "changeme", "todo", "none", "null"}`。

### 实测（真启动 uvicorn，故意全用「错配置」）
```
SC_JWT_SECRET=change-me SC_LLM_PROVIDER=fake SC_SMS_DEV_MODE=true SC_DB_AUTO_CREATE=true
→ 启动日志 5 条：
  启动自检：LLM 使用 fake provider（内置假数据），生成内容不是真实模型输出——仅供演示/测试。
  启动自检：SC_SMS_DEV_MODE=true：任意手机号用验证码 000000 即可注册/登录，且 /auth/wechat/mock-approve 可用——**只能用于本地演示，生产必须关闭**。
  启动自检：SC_PAYMENT_MODE=mock：支付确认不校验真实渠道回调，生产必须改为真实渠道。
  启动自检：SC_ADMIN_INITIAL_PASSWORD 为空：不会创建初始管理员，/admin/* 无法登录。首次部署请设置后再启动（建好后可从环境变量移除）。
  启动自检：SC_JWT_SECRET 仍是默认/测试值：任何人都能伪造登录 token，必须换成随机长串。
/health → {"status":"ok","version":"1.6.0"}（警告不影响启动，符合设计）
```

### 测试（15 项）
基线配置零警告 / 缺密钥 / 占位符 4 值 / fake 不重复抱怨密钥 / SMS dev / mock 支付 /
无管理员 / JWT 默认 4 值 / Postgres+autocreate / **SQLite+autocreate 不报警** /
memory+arq 报警 / memory+inline 不报警。后两条是「不误杀」的反向断言——
只报该报的，否则警告会被当噪音忽略。

### CI 首轮假红：pydantic 小版本让契约漂移（已修）
`export_openapi --check` 在 CI 上红：`openapi.yaml 与代码不一致`，但本地全绿。
根因不是逻辑，是**依赖版本差**：CI 装的是 `fastapi 0.162.3` + `pydantic 2.14.3`，
本机是 `fastapi 0.115.6` + `pydantic 2.14.2`；FastAPI 自动生成的 `ValidationError`
schema 在 pydantic 2.14.3 多了 `ctx` / `input` 两个字段。

```
local(2.14.2)  properties: loc, msg, type
ci  (2.14.3)  properties: ctx, input, loc, msg, type   ← 多 12 行差异
```

修法两层：
1. 导出脚本把 `ValidationError` 规范化成**只承诺 `loc`/`msg`/`type`** 三字段
   （它本来就不是我们定义的契约内容，是框架内部结构；上游加字段不该让我们的
   契约文件变脏）。
2. `backend/pyproject.toml` 给 fastapi 加上界 `>=0.115,<0.163`，并写明理由。

验证：用 venv 装 `fastapi 0.162.2 + pydantic 2.14.3` 跑导出，与本机
`fastapi 0.115.6 + pydantic 2.14.2` 的结果**逐字段完全一致**（`True`）；
两版本跑 `tests/test_openapi_sync.py` 均 5 passed。

## 7. 一键演示脚本（clone 即跑的最短路径）

### 问题
README 的「快速开始」只有 `docker compose up` 一条路：要构建镜像、要 LLM 密钥、
要三个空闲端口。**想先看一眼「它到底能干什么」的人没有 30 秒的路**——
这正好是「从代码可用提升到 clone 即跑、可演示」这个目标的核心缺口。

### 改法
`scripts/demo_local.sh`：SQLite + 进程内队列 + fake provider，随机端口起后端，
跑完 注册 → 下单 → 大纲 → 逐章生成 → 支付确认 → 导出 DOCX，并**校验产物内容**
（AI 参与度披露表 / 免责声明 / 水印 / 章节标题），`trap` 保证退出时杀后端。
CI 里作为独立步骤跑，成了「clone 即跑」的机器门。

### 实测（本机）
```
bash scripts/demo_local.sh
   后端就绪：{"status":"ok","version":"1.6.0"}
   注册 … → 拿到 token（0.4s）
   下单 id=5378… 服务端计价=18000 分（6000 字 × 本科）
   生成大纲 → 5 章（0.5s，模型 fake-model）
   大纲骨架：第一章 绪论 / 第二章 相关理论与技术基础 / 第三章 系统设计与实现 …
   支付 18000 分并确认（mock 渠道）
   逐章生成 5 章完成（1.8s）
   导出 DOCX 39349 字节 → /tmp/scholar-copilot-demo/毕业设计.docx
      AI 参与度披露表: ✓  免责声明: ✓  水印(header): ✓  章节标题: ✓
   订单终态 status=exported，总耗时 3.1s
```
产物校验（独立 zipfile 复核）：18 个 OOXML 部件、document.xml 17,272 字符，
`AI 参与度`/`免责`/`第一章 绪论` 均在；`ss -ltn | grep 8931` 空 → trap 确实回收了进程。

### 脚本自身踩到的坑（已修）
1. `zipfile.ZipFile(...)` 用 `with` 打开后在块外调 `z.read(...)` → `ValueError:
   Attempt to use ZIP archive that was already closed`。把全部 `z.read` 移进 `with` 块。
2. 手机号原用 `str(int(time.time()))[-8:]`，在占位符替换环境里被当成 token；改
   `f"{int(time.time()) % 100000000:08d}"`，仍是合法 11 位号但不含可疑字面。

## 8. 演示数据灌库脚本

### 问题
`docker compose up` 起来是空库，第一次登录的人面对空白页不知道点哪；
「演示」需要一条命令能灌出一份「已经写完的论文」。

### 改法
`scripts/seed_demo.py`：对着运行中的后端跑 账号（先登录，账号不存在才注册——
避免每次吃注册限流）→ 下单 → 大纲 → 支付确认 → 逐章生成 → 导出 DOCX，
打印可直接登录的账号与订单 id。可指定 `--base` / `--title` / `--education` / `--words`。
文档里如实写明：接真实模型会按字数计费、按章数耗时。

### 实测（本机 fake provider，uvicorn:8937）
```
首次：新建演示账号 → 订单 28f8124e…（6000 字 × 本科 = 18000 分）
     大纲 5 章（0.8s）→ 支付 → 逐章 5 章（4.1s）→ 导出 39352 字节
再次：复用已有演示账号（不重复注册）→ 正常再下一单
```

## 9. 未验证项（如实）
- PubMed 在 citecheck 侧的**批量**核查（50 条）未压测；NCBI 匿名 3 req/s 下批量会触发限流，
  生产应配 `SC_PUBMED_API_KEY`（10 req/s）——已写进 .env.example 注释。
- 真实模型下的中间进度帧（`running` 阶段 progress 递增）未在本轮重跑；
  v1.4 已在真模型 + arq 链路上验过 queued→done 两帧与 result 载荷。
- WS 降级路径靠代码逻辑与 `transport` 状态覆盖，未在真实反代（nginx 未配 Upgrade）环境实测。

## 10. 前端样式修复（v1.6.1，headless 截图暴露）

### 问题（真发现，不是猜）
`next build` 退出码 0、8 路由全 200，光看构建日志完全正常。但用
`google-chrome --headless=new --screenshot` 截 `/`（127.0.0.1:3941）得到的
图是**裸 HTML**：导航栏一堆蓝色下划线链接、登录表单无边框无留白、
按钮是系统默认样式——Tailwind 一个类都没生效。

### 根因
`frontend/app/layout.tsx` 的 `<body className="min-h-screen bg-white ...">`
用了一堆 Tailwind 类，但整个文件**没有 `import "./globals.css"`**。
`app/globals.css` 里只有 `@import "tailwindcss";`（Tailwind v4 的入口），
`postcss.config.mjs` 也已配 `@tailwindcss/postcss`——唯独布局没把入口 css 引进来，
于是 Next 构建时根本不生成 utility 样式（构建「成功」是因为语法没错，不是样式对了）。

### 改法
`app/layout.tsx` 顶部加 `import "./globals.css";`。

### 验证（实测）
- 重新 `next build`（`NEXT_PUBLIC_API_BASE=http://localhost:8940`）→ EXIT=0；
- 构建产物出现 `/_next/static/css/ce70facc1cdff91a.css`（**11,993 字节**，
  首行 `/*! tailwindcss v4.3.5 | MIT License ...`）；
- 页面 HTML 带 `<link rel="stylesheet" href="/_next/static/css/...">`；
- 重截登录页：导航栏改为 flex 横排、表单圆角边框、登录按钮深色填充——
  样式正常（`docs/screenshots/login.png`）；
- 同法截 `/workbench`（下单表单/我的订单两栏）、`/review`（体检+改写输入区）、
  `/admin`（管理台登录框）四页，全部样式正常，已入库 `docs/screenshots/`。

### 教训
**构建通过 ≠ UI 可演示**。`next build` 不校验 CSS 是否真的被引入；
以后前端任何改动都要跑一次 headless 截图肉眼确认，不能只看 EXIT=0。
