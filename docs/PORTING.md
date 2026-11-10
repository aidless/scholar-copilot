# PORTING.md — 已有资产移植清单

> 原则：**能搬就不重写**。下表是 aidless 名下仓库 → 本仓库模块的映射。标 ⭐ 的是直接移植对象，标 💡 的是参考实现。

## 1. 写作流水线 → `backend/app/routers/writing.py` + `tasks/worker.py`

**⭐ thesis_auto_generator**（AI 学术写作引擎 v2.2）
- 移植：主题+关键词 → 大纲生成 → 逐章正文 → DOCX 导出
- 关键资产：**A/B/C 三级 AI 参与度标记 + DOCX 水印**——这是本仓库的合规招牌，导出功能以此为准
- 落点：prompt 迁入 `app/prompts/`，生成逻辑进 `tasks/outline_task` / `chapter_task`

## 2. 文献检索与溯源 → `backend/app/routers/references.py`

**⭐ paperKB**（FAISS + SQLite 论文知识库检索）
- 移植：本地论文库向量化检索；作为「系统推荐文献」的库层

**⭐ paper_agent**（论文全流程 Agent：检索/精读/写作/证据链）
- 移植：证据链构建逻辑（引用 → 来源 → 可验证链接）
- 注意：`paper_agent/train/`（Qwen3-4B QLoRA）是独立资产，**不进本仓库**——它是私有微调线，将来作为可选 self-host 模型 provider 单独提供

## 3. 核查面板 → `backend/app/routers/review.py`

**⭐ review-workflow**（16 阶段多 Agent 评审：引用/数字/统计核查）
- 移植：引用核查、数字一致性、统计口径三组规则 → `review_reports.verdict` 的 JSON 结构

**💡 tmaudit**（C1–C10 规则自审 CLI）
- 参考其「规则包 + 零依赖」组织方式；C 类规则可精选进核查面板

**💡 reviewer-sim / agentic-paper-review**
- 多评委交叉裁决思路，v0.4 之后考虑（MVP 先单评委规则版）

## 4. 平台底座 → 后端整体结构

**💡 superagent-platform**（生产级调度：Router 批处理 + token_budget + Watchdog）
- 任务队列的预算控制与外部监督设计，arq worker 落地时参考

**💡 agent-platform**（11 个最小可运行模块，零第三方依赖）
- 骨架期「最小可运行」哲学的来源；本仓库的 501-stub 路由风格同此

## 5. 质量门禁 → `backend/tests/` + CI

**💡 auditable-llm-eval / eval-gate**
- 「每个数字可审计」原则：LLM 输出的评估必须 verifier 与 generator 分离
- 落点：写作质量评测集（E 系列）进 `backend/tests/eval/`，CI 里跑回归门禁

## 6. 不移植的

| 仓库 | 理由 |
|---|---|
| arx / autoresearcher / ai-researcher 系列 | 自主科研循环，与本产品无关 |
| llmtriage / roofline-lint / ttftkit | 推理运维工具线，可在 self-host LLM 文档里引用 |
| mcp-guard / swe-subset | 安全/评测工具线，无关 |

## 移植顺序（对齐 README 路线图）

1. v0.2：thesis_auto_generator（大纲+逐章+导出）→ writing 流水线点亮
2. v0.3：paperKB + paper_agent 证据链 → references 点亮
3. v0.4：review-workflow 规则 → review 点亮
4. v0.5：多租户 + 计费（新写，唯一无存量资产的模块）+ admin RBAC
