# E2E 证据记录 · v1.1（白标多租户 / 分销 / 演示与图表 / PDF）

执行日期：2026-11-10 ｜ 环境：本机 uvicorn 8907，SQLite，LLM=Magpie `group/difficulty-four`

## 一、自动化测试

```
cd backend && python3 -m pytest tests/ -q
→ 40 passed, 1 warning in 40.16s
```

新增 `tests/test_tenant_dist_ppt.py`（6 项）：

| 用例 | 断言要点 | 结果 |
|---|---|---|
| `test_tenant_branding_never_leaks_secrets` | 建租户→配置品牌→Host 解析命中；返回字段 ⊆ 白名单；响应文本不含 secret/token/aeskey/key；未知域回退 primary | PASS |
| `test_distributor_commission_and_withdraw` | 建代理（重复 409）→下单带推广码 36000 分→未支付无佣金→支付后佣金 1800 分/500bps/pending→未结算不可提现→settle 后可提 1800→超额申请 400→admin pay→审计日志含 create/settle/transfer.pay | PASS |
| `test_distributor_login_uniform_401` | 码不存在与手机号不匹配返回同状态码同文案（防枚举） | PASS |
| `test_make_ppt_downloads_pptx` | `PK` 魔数、>20KB、pptx content-type、`.pptx` 文件名 | PASS |
| `test_make_diagram_returns_mermaid` | 返回以 `flowchart` 开头且含中文节点 | PASS |
| `test_export_pdf_real_conversion` | 全链（大纲→支付→逐章→导出 `format=pdf`）→ `%PDF` 魔数 + `application/pdf` | PASS |

## 二、真模型冒烟（真实 LLM + 真实 HTTP）

```
GET /health → {"status":"ok","version":"1.1.0"}
POST /tools/ppt {topic, audience, pages:8} → 200, 37,259 字节, 13.1s
  解包：ppt/slides/slide*.xml = 9 个（1 封面 + 8 内容页）
POST /tools/diagram {description, kind:flowchart} → 200, 17.9s, model=group/difficulty-four, tokens 229→117
  mermaid: flowchart TD A["学生提交论文初稿"] --> B["系统生成大纲"] --> ... --> E["导出 PDF"]
GET /tenant/branding（无 Host）→ primary 回退，无密钥字段
```

## 三、租户与分销闭环（真实服务器，非测试桩）

```
POST /admin/tenants {"name":"云笔学术A","domain":"lab-a.example.com","plan":"pro"} → 201
PUT  /admin/tenants/{id}/config {"brand_color":"#1d4ed8", ...} → 200
GET  /tenant/branding (Host: lab-a.example.com) → tenant_id/name/domain/plan/brand_color/support_contact
     泄露扫描（secret|token|aeskey）→ False
POST /admin/distributors {code:CAMPUS01, rate_bps:500} → 201
POST /writing/orders {price_cents: 36000, distributor_code: CAMPUS01}
POST /payments/orders/{id} + confirm → order_paid: true
GET  /admin/commissions → amount_cents 1800, rate_bps 500, status pending
POST /admin/commissions/{id}/settle → settled, 1800
GET  /distributor/me → balance_cents 1800, withdrawable_cents 1800
```

## 四、PDF 转换（LibreOffice headless）

```
build_thesis_docx(...) 38,776 字节 → docx_bytes_to_pdf → 131,738 字节, 魔数 %PDF, 1.5s
```

## 五、前端构建

```
npm run build（/tmp 副本，规避路径含反斜杠的 ESM 限制）
→ 8 路由：/ /admin /distributor /ppt /references /review /workbench /_not-found
   First Load JS 103–106 kB
```

## 六、迁移

```
alembic upgrade head → e1fecb79f92b (head)
新建 5 表：tenants / tenant_configs / distributors / commissions / distributor_transfers
+ writing_orders.distributor_code 列与索引
```

## 七、已知边界（如实声明）

- 支付仍为 mock/manual 模式，真实商户 webhook 未接（v1.2）。
- 佣金结算只登记状态与余额，真实出款由财务线下执行。
- 任务仍是进程内 asyncio 任务，arq worker 未启用（v1.2）。
- Mermaid 只返回源码，前端未内置渲染器（可用 mermaid.live 或后续加渲染组件）。
- PDF 依赖宿主机 LibreOffice，缺失时 502 并提示改用 docx。
