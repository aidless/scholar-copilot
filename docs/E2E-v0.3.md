# v0.3 端到端冒烟（2026-11-09，Magpie 网关 group/difficulty-four）

启动：`SC_LLM_BASE_URL=http://127.0.0.1:3425/v1 SC_LLM_MODEL=group/difficulty-four SC_LLM_PROVIDER=openai_compat SC_DATABASE_URL="sqlite+aiosqlite:////tmp/sc-e2e/e2e.db" uvicorn app.main:app --port 8907`

## 步骤与实测结果

| 步骤 | 端点 | 结果 |
|---|---|---|
| health | GET /health | `{"status":"ok","version":"0.3.0"}` |
| 注册 | POST /auth/register | token 下发 |
| 真实文献检索 | GET /references/search?q=large language model academic writing&limit=3 | 200，3 条真实条目（Crossref），每条带 DOI/venue/年份，如 "Reimagining academic publications: A meta-model for scholarly writing with large language models"（doi 10.1016/b978-0-443-36775-5.00028-x） |
| 粘贴改写（真模型） | POST /tools/rewrite | 200，61.1s，tokens 271→3259；「综上所述/随着经济/具有重要意义」套话全部清除，替换为可验证表述 |
| 文本体检 | POST /tools/detect | 秒回：套话命中 4 类（密度 139.5/千字）、8-gram 重复 ×3、引用密度 23.3/千字、免责声明在场 |
| 下单→大纲 | POST /writing/orders + /outline?wait=true | 6 章骨架（ch1~ch6） |
| 生成 ch1 | POST /chapters/ch1?wait=true | done，ai_level=A，1841 字 |
| **章节降重（真模型）** | POST /chapters/ch1/rewrite?wait=true instruction="压缩到原来六成篇幅，保留论证结构与引用标记" | done，**1841→1265 字（69%）**，ai_level 保持 A，引用标记 [1] 原位保留 |

## 已修复的冒烟问题

1. **空 API key 崩溃**：`httpx.LocalProtocolError: Illegal header value b'Bearer '`——自托管网关免密钥时 httpx 拒绝尾随空格头。修复 `app/llm/openai_compat.py`：`headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}`。
2. GET /references/search 的 q 参数误用 pydantic Field → 路由注册期断言 `non-body parameters must be in path, query...`。修复：改用 `fastapi.Query`。

## 单测

`python3 -m pytest tests/ -q` → **21 passed**（v0.2 的 14 + v0.3 新增 7：检索 ok/502、挂单+IDOR 404、工具改写、章节改写 A 保持/C→B、后台改写轮询、检测信号、短文本 422）。
