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

## 与已有资产的关系

见 [`docs/PORTING.md`](docs/PORTING.md)——本仓库是多个已有仓库（thesis_auto_generator / paper_agent / paperKB / review-workflow / tmaudit 等）的整合层，不是从零重写。

## 路线图

- [x] v0.1 骨架：monorepo + 建表 + OpenAPI 契约 + SPI 接口
- [x] v0.2 写作流水线（大纲→逐章→改稿→DOCX 导出）：服务端计价、免费大纲 3 次服务端强制（超额 402 + append-only 台账）、AI 参与度 A/B/C 如实标记（生成=A，人工编辑自动升 B，不可关）、导出文档内置披露表 + 免责声明 + 水印；14 项测试 + 真模型端到端冒烟通过
- [x] v0.3 文献检索 + 在线工具：真实查库推荐（OpenAlex 主源 / Crossref 备源 + TTL 缓存，每条带 DOI 可复核，对照闭源产品「百分百真实」口头承诺）、选定文献挂单、粘贴降重改写（LLM）、启发式文本体检（套话/引用密度/重复片段，诚实定性——绝不输出伪精确的「查重率/AIGC 率」）；21 项测试 + 真模型冒烟通过
- [x] v0.4 引用真实性核查 + 格式排版：逐条/批量核查（DOI 直查 + 标题模糊匹配 → verified/suspicious/fake 三态，全带命中证据，不闭环绝不装 verified）；导出支持格式 profile（本科/硕士/博士/英文通用档案，参数透明可查 GET /formatting/profiles）；25 项测试 + 真实 Crossref 核查冒烟通过
- [x] v0.5 支付订单 + 多租户管理端：支付单（服务端价/serial 追踪/mock 网关确认，manual 模式管理员确认，真实商户 webhook 预留 v1.0）；正文生成 402 支付门（大纲免费 3 次）；管理端 JWT RBAC（superadmin/tenant_admin/operator，初始密码仅环境注入、无默认口令）+ 用户/订单/支付/营收统计 + 配额赠送回收（append-only 台账 is_usage 双类行）+ 全动作审计日志；30 项测试 + 真模型支付解锁冒烟通过
- [ ] v1.0 一键自部署文档 + demo 站 + 真实商户回调

## 学术诚信

本项目的产出物默认携带 AI 参与度标记（A=AI 生成 / B=AI 辅助人写 / C=人写）。v0.2 起，导出的每份 DOCX 必带：每页水印「AI 辅助生成 · 仅供参考」、《AI 参与度披露表》（逐章层级 + 字数）与末页免责声明，均不可关闭；用户人工修改 AI 初稿后层级自动从 A 升为 B，如实披露。请遵守所在机构的学术规范——这是设计立场，不是免责声明。

## License

MIT
