# v0.5 端到端冒烟（2026-11-09，Magpie 真模型 group/difficulty-four）

启动：`SC_LLM_BASE_URL=http://127.0.0.1:3425/v1 SC_LLM_MODEL=group/difficulty-four SC_ADMIN_INITIAL_PASSWORD=<线下交付> uvicorn app.main:app --port 8907` → health `0.5.0`

## 支付订单流

| 步骤 | 结果 |
|---|---|
| 下单 6000 字本科 | price_cents=**18000**（服务端价，body 无金额字段可传） |
| 未支付生成正文 | 402 「订单尚未支付…」（单元测试覆盖；冒烟中先触发 409 请先生成大纲，顺序检查正常） |
| 创建支付单 | serial `SCB9A76E85…`、status pending、provider_ref null、pay_url=mock 网关、note 指明真实商户回调 v1.0 |
| 真模型大纲 wait | **58.7s** → outline_done |
| confirm 支付 | status **paid**、provider_ref=`mock-SCB9…`、order_paid=true、paid_at 落库 |
| 支付后生成 ch1 | **解锁**，真模型 58.5s → done / ai_level A / 1854 字 |

## 多租户管理端（RBAC + 审计）

| 步骤 | 结果 |
|---|---|
| POST /admin/login（环境注入密码） | 200，role=superadmin；错密码统一 401（单元测试断言文案一致） |
| GET /admin/stats | users=1 orders=1 jobs=2 payments_paid=1 **revenue_cents=18000** |
| POST /admin/quota/adjust +2 | remaining 2→**4**（limit3 − used1 + granted2，is_usage 双类行台账） |
| POST /admin/quota/adjust −1 | remaining 4→**3** |
| GET /admin/audit-log | 两条 quota.adjust 全带 target/detail/reason |
| GET /admin/payments?status=paid | SCB9A76E85… 18000 paid |
| 用户 token 访问 /admin/stats | **403** 需要管理员权限 |

## 单测

`python3 -m pytest tests/ -q` → **30 passed**（v0.4 的 25 + v0.5 新增 4 文件级用例：支付流 402→解锁→重复 409、支付 IDOR、admin 登录 RBAC/防枚举、配额调整+审计+列表）。

## 台账语义（修复记录）

QuotaLedger 原实现「余额=limit−Σ(全部 delta)」会把管理员赠送行当消耗。v0.5 加 `is_usage` 列：消费/冲正行 is_usage=true，管理员赠送/回收行 is_usage=false，余额 = limit − Σ(is_usage) + Σ(NOT is_usage)。init.sql（PG）与模型（SQLite）同步。
