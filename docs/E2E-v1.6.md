# E2E 证据：v1.6 检索四源 + 任务进度 WebSocket

日期：2026-11-10　版本：1.6.0　测试：**74 passed**

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

## 3. 未验证项（如实）
- 真实模型下的中间进度帧（`running` 阶段 progress 递增）未在本轮重跑；
  v1.4 已在真模型 + arq 链路上验过 queued→done 两帧与 result 载荷。
- WS 降级路径靠代码逻辑与 `transport` 状态覆盖，未在真实反代（nginx 未配 Upgrade）环境实测。
