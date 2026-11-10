# v0.4 端到端冒烟（2026-11-09，真实 Crossref + fake provider）

启动：`SC_LLM_PROVIDER=fake SC_DATABASE_URL="sqlite+aiosqlite:////tmp/sc-e2e/e2e.db" uvicorn app.main:app --port 8907` → health `0.4.0`

## 引用真实性核查（真实网络）

POST /references/verify 三条实测：

| 输入 | 判定 | 证据要点 |
|---|---|---|
| "Attention Is All You Need" + DOI 10.5555/3295222.3295234（ACM 前缀，Crossref 未收录）+ year 2017 | **suspicious**（0.905） | DOI 查无→标题匹配命中 "Is Attention All You Need?"（2025，venue From Human Attention to Computational Attention），year_mismatch=2017 → 如实降级，**不装 verified** |
| "Reimagining academic publications: A meta-model for scholarly writing with large language models" year 2026 | **verified**（1.0） | 标题精确命中，doi 10.1016/b978-0-443-36775-5.00028-x，年份一致 |
| "这是一篇完全编造不存在的论文关于量子猫计划的超级研究" | **fake**（0.162） | 候选 3 条均 <0.55 阈值，matched_title=null |

注：NeurIPS 2017 原文无 Crossref DOI（会议论文集未注册），核查器不因此误报 fake，而是给 suspicious + 命中证据供人工判断——这是三态设计的价值。

## 格式排版

- GET /formatting/profiles → 4 档：本科-通用 / 硕士-通用 / 博士-通用 / 英文-通用（参数全透明：正文字体字号行距/三级标题/页边距）。
- 单测覆盖：profile 导出 PK 魔数 >10000 字节；未知 profile 422 并提示可用值。

## 单测

`python3 -m pytest tests/ -q` → **25 passed**（v0.3 的 21 + v0.4 新增 4：verify 端点+502、订单批量核查+行更新+IDOR+空文献409、格式档案列表、profile 导出+未知422）。
