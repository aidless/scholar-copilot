# v0.2 端到端冒烟证据（2026-11-09）

环境：uvicorn 127.0.0.1:8907 + sqlite /tmp/sc-e2e/e2e.db + Magpie 网关真模型
（SC_LLM_MODEL=opencode-go/deepseek-v4.1-flash，SC_LLM_BASE_URL=http://127.0.0.1:3425/v1）

| 步骤 | 结果 |
|---|---|
| POST /auth/register（dev 短信码 000000） | 200，JWT 签发 |
| POST /writing/orders 本科/12000字 | price_cents=36000（0.03元/字×12000×100，服务端算） |
| POST /writing/orders/{id}/outline?wait=true | job done，33.2s，tokens 524→2200，6 章解析成功，order→outline_done |
| GET /writing/orders/{id}/chapters | ch1~ch6 骨架（第一章 绪论 … 第六章 总结与展望），pending/ai_level C |
| POST chapters/{ch1..ch6}?wait=true | 全部 done：2766/3161/2691/3095/3288/2997 字，ai_level A |
| 订单状态 | writing_done |
| PUT chapters/ch1（人工改稿） | ai_level A→B（自动如实升级），word_count 重算 |
| POST /writing/orders/{id}/export | HTTP 200，60122 字节，Content-Disposition filename*=UTF-8 |
| DOCX 解包验证 | header1.xml 含水印「AI 辅助生成 · 仅供参考」；document.xml 含《AI 参与度披露表》、三级层级文案（人工撰写/AI 生成未经修改/AI 初稿人工已修改）、免责声明、品牌标识、全部章标题 |

单测：backend `pytest tests/ -q` → **14 passed**（auth 6 + writing 7 + health 1），
覆盖：统一 401 防枚举、409 重复注册、422 格式、服务端计价（客户端价忽略）、
IDOR 统一 404、配额第 4 次 402、导出前置校验 409、job 轮询属主校验。
