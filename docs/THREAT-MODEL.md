# THREAT-MODEL.md — 安全默认与威胁模型

> 来源：blsxueshu.com 逆向实测的四个系统性漏洞。每一条在本仓库都有对应的结构性修复，不是「注意事项」而是代码/库表约束。

## 修复映射表

| # | 实测漏洞（原产品） | 本仓库修复 | 落点 |
|---|---|---|---|
| 1 | 订单接口只验登录不验属主，跨租户任意读（IDOR） | 所有用户资源表 `tenant_id + owner_id` 双列 + 复合索引；查询必须过 `ownership_filter()` | `deploy/init.sql`（R1）、`app/tenancy.py` |
| 2 | `websiteInfo` 匿名返回租户 wxAppSecret/smsSignCode 等 8 类密钥 | 密钥只进 `pgcrypto` 加密列；响应序列化层禁止 secret 字段（模型层就没有明文字段） | `tenant_configs.*_enc` 列 |
| 3 | 管理台 `/admin/*` 匿名可读 + 5/8 租户口令 `123456` | admin JWT 独立签发 + RBAC 角色 + `admin_audit_log` 全量留痕；初始密码随机生成线下交付 | `routers/admin.py`、`admin_users` 表 |
| 4 | 短信签名 = sha256(静态盐+手机号)，离线可复算 + 注册状态 oracle | HMAC-SHA256(时间窗+手机号)，密钥服务端持有；验证码一次性、5 分钟过期、按手机号限流 | `app/security.py::sms_signature` |

## 其他默认安全决策

- **密码**：bcrypt 服务端哈希（原产品客户端 MD5 直传，哈希即密码）。
- **枚举防护**：对象不存在与不属你统一返回 404（原产品错误态差分可枚举账号）。
- **算价/算配额只在服务端**：前端传价格/配额字段一律忽略；配额走 append-only 台账，余额 SUM 可审计。
- **LLM 用量透明**：每次生成记录真实 token 用量（`generation_jobs.tokens_*`），计费与展示同源。
- **JWT**：HS256 + 部署时必须显式设置 `SC_JWT_SECRET`（.env.example 注明），7 天过期；admin token 独立短时效。

## 威胁清单（MVP 明确不防的）

| 威胁 | 状态 | 计划 |
|---|---|---|
| 管理台 XSS → 会话窃取 | MVP 依赖 Next.js 默认转义 + CSP 待配 | v0.5 加 CSP 与 HttpOnly cookie 方案 |
| LLM prompt 注入（用户投喂材料里藏指令） | 未防护 | v0.2 投喂材料进沙箱解析 + 指令剥离后再入 prompt |
| 支付回调伪造 | 未实现支付前不适用 | v0.5 验签 + 幂等 + 金额以服务端单据为准 |
| 分布式撞库登录 | 未防护 | v0.2 登录限流（IP+手机号双维度） |

## 自查清单（每个 PR 过一遍）

1. 新增的 SELECT 是否过了 `ownership_filter`？
2. 新增的响应模型是否可能带出 `*_enc` 或 key 类字段？
3. 新增的写操作是否记 `admin_audit_log`（若属管理动作）？
4. 生成类任务是否记录了真实 token 用量？
