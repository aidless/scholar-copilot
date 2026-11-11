# E2E 报告 v1.12 —— 商业化 + 差异化十项

> 口径：所有数字来自本机实跑（SQLite + fake provider，或 pytest）。凡未实测的项在末节如实列出。
> 本轮对应 22 项清单里最后剩下的 10 项（#8 #10 #14 #15 #16 #17 #18 #19 #20 #21）。

---

## 一、内容指纹链（#19）：AI 参与度从「自证」变「可审计」

**问题**：原实现里 `ai_level` 是章节上的一个字符串，用户标 C（人写）就是 C，系统无法验证；
而「AI 参与度披露」是学术诚信的核心卖点，靠自证等于没有。

**做法**：`backend/app/provenance.py` + `generation_provenance` 表（迁移 `c3d4e5f6a7b8`）。

- `fingerprint(text)`：sha256，**先去掉所有空白再算**——否则用户改个换行就换了指纹，链条失去意义。
- `diff_ratio(a, b)`：`SequenceMatcher`，双空视为 1.0、单空视为 0.0（普通相似度函数在这两种边界上会给出反直觉结果）。
- `record_event(...)`：生成/改写/改稿各写一行，`prev_content` 存在时算 `sim_to_prev`。
- 写入点：`tasks/local.py` 的 `_run_outline`（kind=outline）、`_run_chapter`（kind=generate）、`_run_rewrite`（kind=rewrite）；`writing.py::edit_chapter`（kind=edit，actor=用户 id）。
- 读取：`GET /writing/orders/{id}/provenance` → `{order_id, chain[{node_id,kind,content_sha256,word_count,ai_level,similarity,actor,created_at}], latest_levels, human_edited_nodes, disclaimer}`。

**实测**：`tests/test_provenance.py` 6 项 + `tests/test_provenance_api.py` 4 项通过。
API 用例覆盖「生成后链条里有 outline → 改稿后追加一条 edit 且 `human_edited_nodes` 命中 → 非属主 404」。

---

## 二、引用证据链 Top-N（#20）：0.905 这个数字要能点开看

**问题**：原来 `verify_citation` 只返回最佳候选的相似度（如 `suspicious 0.905 crossref`），
用户看不出「为什么不是 1.0」「还有哪些候选」，等于给了一个不可复核的判决。

**做法**：`backend/app/citecheck.py` 新增 `DEFAULT_TOP_K = 5` 与 `_rank_candidates()`：

- 用**与判定同一把尺子**（同一个 `_similarity`）给所有候选打分，避免「判决用一个算法、展示用另一个」；
- 统一形状 `{title, year, venue, doi, source, similarity}`，按相似度降序截断；
- DOI 直查命中时单条 `similarity=1.0`（这就是「确切匹配」的形态）；
- 缓存 key 加 `|{top_k}`（否则先请求 top_k=3 的会污染 top_k=5 的结果）。

端点：
- `POST /references/verify/evidence` —— 批量核查，每条结果带 `candidates` 与 `chart`（条形图规格）；
- `POST /references/verify/evidence/chart` —— 直接把规格渲染成 PNG（`export/charts.py`），无候选 404；
- `GET /references/orders/{order_id}/evidence` —— 已核查订单的证据快照（`verify_evidence["candidates"]`）。

**实测**：`tests/test_citecheck_evidence.py` 6 项（先 RED 6 failed 再 GREEN）。

---

## 三、真查重 / AIGC 可解释自查（#8）

**问题**：原 `/tools/detect` 是启发式判「AI 味」，且免责声明写着「仅供参考」——用户拿不到任何可核对的东西。

**做法**：`backend/app/similarity.py`

- `tokenize()`：CJK 二元组 + 拉丁词（中文查重不能用空格切词）；
- `match_fragments(text, reference, min_len)`：去空白后逐位置匹配，双向扩展到最长公共段，重叠合并取最长 10 条，返回 `{fragment, text_start, length, ref_start}` —— 用户能**直接定位到第几个字**；
- `selfcheck(text, references)`：`verdict`（≥0.3 high / ≥0.1 moderate / else low）+ `max_overlap_ratio` + 每篇文献的 `overlap_ratio/overlap_chars/cosine/fragments`；
- `aigc_features(text)`：5 类特征（套话密度、句长变异系数、连接词密度、平均句长、结构标记密度）**每条带 evidence 原文片段**。

**实现 bug（记在这里，避免重犯）**：初版 `match_fragments` 固定 `min_len=20`，
短文本（测试用的 12 字重复句）永远命中不了 → `test_selfcheck_verdict_flags_high_overlap` 红。
修法：`eff_min = min(20, max(8, min(len_text, len_ref) // 2))` 自适应阈值。

**实测**：`tests/test_similarity.py` 12 项 + `tests/test_selfcheck_api.py` 5 项。

---

## 四、学校模板库（#10）

**问题**：原来只有 4 个通用 `FORMAT_PROFILES`（默认/紧凑/宽松/期刊），学校格式无从配置。

**做法**：`backend/app/export/templates.py`

- `validate_spec()` **严格校验**：缺字段直接 `ValueError`，**不静默补默认值**——静默补默认会让用户以为「已经按学校格式排了」；
- 范围护栏：字号 8–36pt、行距 1.0–3.0、页边距 0.5–6.0cm；
- `BUILTIN_TEMPLATES` 四套（`示例-清华-硕士`/`示例-北大-博士`/`示例-浙大-本科`/`示例-通用-期刊投稿`），**label 或 note 必含「示例」二字**：不声称是官方规范（这也是本项目的诚信底线）；
- `format_templates` 表（迁移 `d4e5f6a7b8c9`）+ 管理端 `POST/GET/DELETE /admin/format-templates`（租户内 key 冲突 409，创建/删除都写审计）；
- `writing.py::export_order` 用 `resolve_profile(db, key)` 同时解析内置与租户自建，未知 422 并提示 `GET /formatting/profiles`。

**实测**：`tests/test_format_templates.py` 7 项（先 RED 7 failed）。既有 `tests/test_citecheck_formatting.py`
里「profiles 恰好等于四条」的断言随之放宽为「原四条 ⊆ profiles」（新增模板不该让旧断言红）。

---

## 五、token 级计费（#18）

**问题**：原来计费只到「订单付了多少钱」，不知道钱花在哪个任务、哪个模型上，也没有套餐与余额。

**做法**：`backend/app/billing.py` + 三张表（迁移 `e5f6a7b8c9d0`）

| 表 | 作用 |
| --- | --- |
| `usage_records` | 每次 LLM 调用一行：kind/model/tokens_in/tokens_out/cost_cents |
| `accounts` | 用户账户：plan_key / balance_cents / token_quota / tokens_used |
| `account_ledger` | 充值/订阅/拼团流水，append-only |

- `cost_cents()` **不另立价格表**，直接复用 `llm.router.COST_TABLE`——否则路由换了模型、账单还是旧价，两边必然对不上。
- `record_usage()` 记账失败只 warning，**不回滚已经生成的内容**（记账是旁路，不能绑架主流程）。
- `/billing/plans|usage|account`、`POST /billing/account/topup`、`POST /billing/plans/{key}/subscribe`（未知套餐 404、余额不足 402）。

**实测**：`tests/test_billing_usage.py` 11 项。成本断言用「同模型 token 翻倍 → 成本变大」，
而不是钉死某个具体分值（价表一改，钉死的断言就假红）。

---

## 六、兑换码 / 拼团（#17）

- `POST /billing/redeem`：一码一用（重复用 409）、不存在 404、过期 410；
- `POST /billing/group-buys`（201 开团）、`POST /billing/group-buys/{id}/join`、`GET /billing/group-buys/{id}`；
- **满员结算语义**：先全员余额校验，任一不足 402 且**整团不结算**（避免「部分人扣钱、团没成」）；
  成功后每人按 `group_price_cents` 扣款写 `group_buy` 流水并升套餐；已结算 409、过期 410；
- 管理端 `POST /admin/redeem-codes` 批量生成（`"SC" + token_hex(5).upper()`）+ `GET /admin/redeem-codes?batch=`。

**实测**：`tests/test_redeem_groupbuy.py` 9 项。

---

## 七、离线模式 + 本地文献库（#21）

**问题**：内网/无外网环境下，四源检索全部超时，产品直接不可用。

**做法**：`SC_OFFLINE_MODE=true` + `backend/app/offline.py` + `local_references` 表（迁移 `g7b8c9d0e1f2`）

- `parse_bibtex()`：处理 `@article{key, title={...}, author={A and B}, year=2020, doi=...}`（花括号嵌套与 `and` 作者分隔）；
- `parse_cnki()`：处理制表符/多条空行分隔的题录导出；
- `search_local()`：标题相似度（同样的二元组余弦）排序；
- `verify_local()`：**离线态不下 fake 判决**——未命中返回 `unverified` 并说明「本地库未收录」，
  因为在离线环境里「查不到」不等于「不存在」，判 fake 是错误的知识主张；
- `/references/library`（导入、列表、检索），按 `title+year` 去重并返回 `imported/skipped`。

**两个实测暴露的缺陷（都已修，且都是「看起来能用其实是假的」）**：

1. **单行 BibTeX 解析不出来**：原实现用 `@(\w+)\{...,(.*?)\n\}` 整段匹配，要求条目以「换行 + }」收尾；
   真网络实测把一条标准单行 BibTeX 粘进去 → `422 未解析出任何条目`。
   修法：改成花括号配对扫描（`_iter_bib_entries` + `_bib_fields`），单行/多行/嵌套花括号/引号值/裸年份一律通吃。
2. **检索只是子串匹配**：查 `offline design` 找不到 `Offline First Design`（词序不同即零命中），
   等于「离线状态下没有检索」。修法：先子串命中（精确优先），再按查询词覆盖率补一层
   （Latin 按词、CJK 按二元组；覆盖率 ≥0.5 才收），既救回词序调换，也不会把无关条目捞进来。

**实测（离线模式 `SC_OFFLINE_MODE=true` 真网络）**：

| 请求 | 结果 |
| --- | --- |
| `POST /references/library/import`（单行 BibTeX） | 201 `{"imported":1,"skipped":0}`；重复导入 201 `{"imported":0,"skipped":1}` |
| `POST /references/library/search {"q":"offline design"}` | 命中 `Offline First Design`（`library_size:1`） |
| `POST /references/verify`（库内标题） | `verified` similarity 1.0，`evidence.source="local"` |
| `POST /references/verify`（库外标题） | `unverified` similarity 0.0606，`hint="本地库未命中；离线模式不判定文献真伪"` |
| `GET /references/search?q=offline+design` | `source: "local"`，返回本地条目（不出网） |

单元测试：`tests/test_offline_library.py` **20 项**（含新增 4 项单行 BibTeX 回归 + 4 项检索回归）。

---

## 八、导出产物入对象存储（#14）

- 每次导出后 `storage.save(make_key("exports/{tenant}", ext), data)` 并落 `export_artifacts`（迁移 `h8c9d0e1f2a3`）；
- 响应头带 `X-Export-Id`；`GET /writing/orders/{id}/exports`（倒序）、`GET /writing/exports/{id}/signed-url`、`GET /writing/exports/{id}/download`；
- 归档失败只 warning、仍返回文件流（不能因为归档坏了就让人拿不到论文）。

**实现 bug（记下来）**：`ExportArtifact.id` 是 Python 侧 `default=_uuid`，
`db.add()` 之后不 `flush()` 的话 `artifact.id` 还是 `None` → 响应头静默缺失，测试只报「没有 X-Export-Id」。
修法：`await db.flush()` 再取 id。

**实测**：`tests/test_export_artifacts.py` 4 项（含「下载字节 sha256 与首次导出一致」与「他人 404」）。

---

## 九、管理台补 UI（#16）

`frontend/app/admin/page.tsx` 新增四块（此前这 8 个端点只有 API 没有界面）：

- 租户：列表（id/名称/域名/套餐/状态/余额）+ 「新建租户」；
- 分销商：列表（名称/推广码/电话/佣金率/余额/状态）+ 「新建分销商」（万分比输入，500 = 5%）；
- 佣金：列表 + 仅 `pending` 可「结算」；
- 提现审核：列表 + 仅 `pending` 可「通过 / 驳回」。

`reload()` 从 5 个并发请求扩到 9 个，四张表随统计一起刷新。

---

## 十、i18n（#15）

**范围取舍**：不做 next-intl 全量路由改造（单仓自部署工具、用户群基本中文，收益不匹配成本）。
真正影响产出的只有两处，就只做这两处：

1. **生成语言**：`outline_system_prompt(lang)` / `chapter_system_prompt(lang)`
   —— `order.language == "en"` 时送英文系统提示（`OUTLINE_SYSTEM_PROMPT_EN` / `CHAPTER_SYSTEM_PROMPT_EN`），未知语言回落中文；
2. **外发文案**：`backend/app/i18n.py` 的目录（日报主题/字段名、导出与审计免责声明），`t(key, lang)`、`catalog(lang)`。

前端 `frontend/lib/i18n.ts`：`useT()` + localStorage 持久化，首页导航与语言切换按钮接入。

**实测**：`tests/test_i18n.py` 15 项（含「英文提示必须真的是英文指令」——否则「切语言」是假的）。

---

## 十一、收尾验证

| 项 | 结果 |
| --- | --- |
| 后端全量 | `python3 -m pytest tests/ -q` → **297 passed, 1 skipped**（唯一 skip 为「本机无 TeX 时跳过真实编译」，CI 装了 texlive 会真跑） |
| 迁移一致性门 | `tests/test_migrations_match_models.py` 通过；`alembic heads` 单头 `h8c9d0e1f2a3` |
| OpenAPI 契约 | 重导出 **98 路径 / 43 schema**（version 1.12.0），`tests/test_openapi_sync.py` 5 项通过 |
| 前端构建 | `/tmp` 副本 `npx next build` EXIT=0，8 路由（First Load JS 103–107 kB） |

---

## 十二、未验证项（如实列出）

1. **S3 后端未接真桶**：`storage.py` 的 S3 分支只在单测里被 monkeypatch 覆盖，未对真实 MinIO/S3 跑过；本地 `s3://` 签名 URL 未实测。
2. **拼团结算未做并发压测**：语义上「先校验全员余额再扣」已在单测覆盖，但两个 join 请求同时到达时的竞态（同团双结算）没有专门测试，也未加行锁。
3. **兑换码未做批量导出/作废接口**：目前只能建与查。
4. **i18n 只覆盖骨架**：写作台/文献页的中文文案未抽词条；英文下的导出 DOCX 模板（页眉水印、披露表）仍是中文，只切了正文生成语言。
5. **离线库只支持 BibTeX 与 CNKI 题录**：EndNote `.enw`、RIS 导入未做。
6. **管理台四块 UI 只做了功能**：无分页、无搜索、无排序（列表全量渲染，`limit` 由后端 300 兜底）。
