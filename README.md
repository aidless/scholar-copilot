# Scholar Copilot

**开源的学术写作 Copilot**：文献检索 → 引用溯源 → 大纲/逐章辅助写作 → 引用/数字核查 → 多租户自部署。

> 定位声明：这是一个**写作辅助工具**，不承诺「过查重」、不代写。所有 AI 参与的内容默认携带 A/B/C 三级参与度标记，符合生成式内容标识的合规方向。

## 为什么做这个

市面上同类商业产品（以 blsxueshu.com / okbiye 白标系为代表）是闭源 SaaS。逆向分析发现它的四个系统性问题，本项目从第一行代码起就反向设计：

| 闭源产品的问题（实测） | 本项目的默认设计 |
|---|---|
| 管理台大面积无鉴权，8 租户口令泄露 | 管理台强制 RBAC + 独立会话，见 `docs/THREAT-MODEL.md` |
| 订单接口只验登录不验属主（跨租户 IDOR） | 所有资源查询强制 `tenant_id + owner_id` 双列过滤（数据库层约束） |
| `websiteInfo` 接口明文吐出租户微信/短信密钥 | 密钥只存服务端加密列，任何对外 API 不返回 secret 字段 |
| 短信签名 = sha256(静态盐+手机号)，可离线复算 | 短信签名 = HMAC-SHA256(时间戳+手机号, 服务端密钥)，5 分钟有效 |

另外一个核心差异：**LLM 可插拔**。原产品模型与 prompt 锁死在服务端黑盒里；本项目所有生成走统一的 Provider SPI，接 OpenAI 兼容 API / DeepSeek / Qwen / 本地 vLLM 只改一行配置，prompt 全部开源可审计。

## 架构

```
frontend (Next.js)  ──HTTP──▶  backend (FastAPI)
                                 ├─ tenancy.py      ← 域名/头 → 租户路由 + 属主校验
                                 ├─ routers/        ← auth / writing / references / review / billing / admin
                                 ├─ llm/            ← Provider SPI（openai-compat / 本地 vLLM / Ollama）
                                 ├─ tasks/ (arq)    ← 大纲、逐章、核查的异步任务队列
                                 └─ PostgreSQL      ← deploy/init.sql（含租户/属主列约束）
references 模块复用 paperKB (FAISS+SQLite) + paper_agent 证据链
review 模块复用 review-workflow / tmaudit 的核查规则
```

## 快速开始

```bash
cp .env.example .env          # 填 LLM_API_KEY 等
docker compose up -d          # postgres + redis + backend + frontend
# backend http://localhost:8000/docs   frontend http://localhost:3000
```

本地开发：

```bash
cd backend && pip install -e ".[dev]" && uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
```

生产部署（迁移 / TLS / 限流 / 备份）与常见问题：见 [`docs/DEPLOY.md`](docs/DEPLOY.md)。

## 工程加固（v1.0）

| 项 | 做法 |
|---|---|
| 暴力破解 | 登录/注册按 IP 限流（默认 20 次/分），429 + `Retry-After`；密码统一 401 文案防枚举 |
| LLM 成本滥用 | `/tools/rewrite`、`/tools/detect` 单独限额（默认 10 次/分） |
| 前端越权调用 | CORS 白名单（`SC_CORS_ORIGINS`），非白名单来源无 `Access-Control-Allow-Origin` |
| prompt 注入 | 用户文本一律 `wrap_untrusted()` 包裹：边界声明 + 哨兵中和（`<<<`/`>>>`/围栏/哨兵词），有逃逸单测 |
| 数据库演进 | alembic 迁移（`migrations/versions/64bfd6724d4e`），生产 `SC_DB_AUTO_CREATE=false` |
| 交付形态 | 后端/前端 Dockerfile + compose 一键起；CI 跑 pytest + 空库迁移 + 前端 build |

## 与已有资产的关系

见 [`docs/PORTING.md`](docs/PORTING.md)——本仓库是多个已有仓库（thesis_auto_generator / paper_agent / paperKB / review-workflow / tmaudit 等）的整合层，不是从零重写。

## 路线图

- [x] v0.1 骨架：monorepo + 建表 + OpenAPI 契约 + SPI 接口
- [x] v0.2 写作流水线（大纲→逐章→改稿→DOCX 导出）：服务端计价、免费大纲 3 次服务端强制（超额 402 + append-only 台账）、AI 参与度 A/B/C 如实标记（生成=A，人工编辑自动升 B，不可关）、导出文档内置披露表 + 免责声明 + 水印；14 项测试 + 真模型端到端冒烟通过
- [x] v0.3 文献检索 + 在线工具：真实查库推荐（OpenAlex 主源 / Crossref 备源 + TTL 缓存，每条带 DOI 可复核，对照闭源产品「百分百真实」口头承诺）、选定文献挂单、粘贴降重改写（LLM）、启发式文本体检（套话/引用密度/重复片段，诚实定性——绝不输出伪精确的「查重率/AIGC 率」）；21 项测试 + 真模型冒烟通过
- [x] v0.4 引用真实性核查 + 格式排版：逐条/批量核查（DOI 直查 + 标题模糊匹配 → verified/suspicious/fake 三态，全带命中证据，不闭环绝不装 verified）；导出支持格式 profile（本科/硕士/博士/英文通用档案，参数透明可查 GET /formatting/profiles）；25 项测试 + 真实 Crossref 核查冒烟通过
- [x] v0.5 支付订单 + 多租户管理端：支付单（服务端价/serial 追踪/mock 网关确认，manual 模式管理员确认，真实商户 webhook 预留 v1.0）；正文生成 402 支付门（大纲免费 3 次）；管理端 JWT RBAC（superadmin/tenant_admin/operator，初始密码仅环境注入、无默认口令）+ 用户/订单/支付/营收统计 + 配额赠送回收（append-only 台账 is_usage 双类行）+ 全动作审计日志；30 项测试 + 真模型支付解锁冒烟通过
- [x] v1.0 工程加固（可一键自部署）：Dockerfile×2 + docker-compose（healthcheck/依赖顺序/env 内联）+ alembic 初始迁移（10 表，空库 upgrade head 通过）+ 三层限流（登录/LLM/检索，429+Retry-After）+ CORS 白名单 + prompt 注入结构化定界（哨兵+中和，含逃逸单测）+ GitHub Actions CI（后端 pytest + alembic 落地 + 前端 typecheck/build）+ 真正可用的 Web UI（登录/写作台/文献/体检/管理台 6 路由）+ `docs/DEPLOY.md`；34 项测试通过、容器内 /health 与注册冒烟通过
- [x] v1.1 白标多租户 + 分销 + 演示与图表：按域名解析租户、`GET /tenant/branding` 只暴露品牌白名单（名称/配色/Logo/客服，绝不返回渠道密钥——正面修复原产品 websiteInfo 泄露洞）；分销代理（推广码登录、佣金=服务端价×万分比、只在订单支付成功时生成、结算/提现全走审计日志）；`POST /tools/ppt` 生成可编辑 PPTX、`POST /tools/diagram` 输出 Mermaid 源码（不返回黑盒图片）；`POST /orders/{id}/export?format=pdf` 真实 LibreOffice 转换；新增 alembic 迁移 e1fecb79f92b（5 表 + writing_orders.distributor_code）；40 项测试通过（含 PDF 真实转换与租户不泄密断言）
- [x] v1.2 认证与任务层：短信验证码改为「随机码 + SHA-256 摘要入库 + 5 分钟过期 + 限 5 次尝试」，且**不对手机号注册状态做分支响应**（正面修复原产品静态盐 sign 的注册状态枚举 oracle）；网关抽象 `dev|http` 两驱动；微信扫码登录（dev 可 mock 确认，生产需 `SC_WECHAT_APP_ID/SECRET`）；任务队列抽象 `SC_TASK_QUEUE=inline|arq`——端点统一 `enqueue()`，切 arq 即交独立 worker（`arq app.tasks.worker.WorkerSettings`），端点契约不变；45 项测试通过
- [x] v1.3 导出与运营报表：LaTeX 导出（`export?format=tex`，ctexart 单文件，特殊字符转义、披露表与免责声明同在）；管理端对账 CSV 导出（订单/支付/佣金/审计四类，UTF-8 BOM、导出动作留审计）；前端补微信扫码入口（dev 模拟确认）与管理台 CSV 按钮；47 项测试通过
- [ ] v1.4 计划：OpenAlex 带 key 提高配额、引用核查接入多源（Semantic Scholar/PubMed）、任务进度 WebSocket、审计报表定时推送

## 学术诚信

本项目的产出物默认携带 AI 参与度标记（A=AI 生成 / B=AI 辅助人写 / C=人写）。v0.2 起，导出的每份 DOCX 必带：每页水印「AI 辅助生成 · 仅供参考」、《AI 参与度披露表》（逐章层级 + 字数）与末页免责声明，均不可关闭；用户人工修改 AI 初稿后层级自动从 A 升为 B，如实披露。请遵守所在机构的学术规范——这是设计立场，不是免责声明。

## License

MIT
