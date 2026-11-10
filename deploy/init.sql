-- Scholar Copilot 建表蓝本 v0.1（PostgreSQL 16）
-- 来源：blsxueshu.com 逆向还原的 14 张表数据模型 + 四个安全洞的结构性修复
-- 设计规则（每条对应逆向报告实测漏洞）：
--   R1  所有用户资源表必须带 tenant_id + owner_id 双列并建复合索引（修跨租户 IDOR）
--   R2  密钥只进加密列（pgcrypto），任何视图/API 不暴露（修 websiteInfo 泄密）
--   R3  管理端独立于用户端表空间之外做 RBAC（修管理台裸奔）
--   R4  计费/配额只在服务端写（修「配额仅前端展示」的歧义）

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============ 租户与平台 ============

-- 租户（白标站点）。原产品 8 租户共享后端、domain 参数路由租户库；这里一行一个站
CREATE TABLE tenants (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name          text NOT NULL,                    -- 站点名，如「某某学术」
    domain        text NOT NULL UNIQUE,             -- 解析域名，含子域
    plan          text NOT NULL DEFAULT 'free',     -- free / pro / enterprise
    balance_cents bigint NOT NULL DEFAULT 0,        -- 平台侧余额（分）
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- 租户三方配置。secret 一律 pgcrypto 加密落库；SELECT 层永远不返回明文列
CREATE TABLE tenant_configs (
    tenant_id        uuid PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    wx_app_id        text,
    wx_app_secret_enc bytea,                         -- 修复点：绝不进任何对外响应
    sms_provider     text,
    sms_key_enc      bytea,
    pay_mch_id       text,
    pay_key_enc      bytea,
    llm_base_url     text,
    llm_key_enc      bytea,                          -- 每租户可插拔自己的 LLM
    updated_at       timestamptz NOT NULL DEFAULT now()
);

-- ============ 用户与鉴权 ============

CREATE TABLE users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES tenants(id),
    phone         text NOT NULL,
    pass_hash     text NOT NULL,                    -- bcrypt，服务端算（原产品客户端 MD5 直传）
    display_name  text,
    invitee_id    uuid REFERENCES users(id),        -- 分销链
    commission_bp int  NOT NULL DEFAULT 500,        -- 佣金基点(bp)，5%=500；透明可查
    status        text NOT NULL DEFAULT 'active',   -- active / banned
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, phone)
);
CREATE INDEX idx_users_tenant ON users(tenant_id);

-- 配额台账：append-only，两类行——
--   is_usage=true  : 消费(+1)/失败冲正(-1)，净额=已用
--   is_usage=false : 管理员赠送(+n)/回收(-n)，净额=额外配额
-- 余额 = free_limit - Σ(is_usage) + Σ(NOT is_usage)，可审计
CREATE TABLE quota_ledger (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id   uuid NOT NULL REFERENCES tenants(id),
    kind        text NOT NULL,                      -- outline / chapter / image / check
    delta       int NOT NULL,
    is_usage    boolean NOT NULL DEFAULT true,
    reason      text NOT NULL,                      -- free_grant / order_pay / consume / admin_grant
    ref_id      text,                               -- 关联订单/任务
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_quota_user ON quota_ledger(user_id, kind);

-- ============ 写作核心 ============

-- 写作订单（对应原 ai_writing_orders，字段按 API 实测反推）
CREATE TABLE writing_orders (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_no         bigint NOT NULL UNIQUE,        -- 展示用单据号（雪花），不作为检索键
    tenant_id        uuid NOT NULL REFERENCES tenants(id),
    owner_id         uuid NOT NULL REFERENCES users(id),   -- 修复点 R1：属主列 + 复合索引
    title            text NOT NULL,
    education        text NOT NULL,                 -- 本科/硕士/博士
    word_count       int  NOT NULL,
    language         text NOT NULL DEFAULT 'zh',
    writing_type     text NOT NULL DEFAULT 'thesis',-- thesis / literature_review / proposal ...
    price_cents      int  NOT NULL,                 -- 服务端算（billing.quote 公式），前端传值无效
    status           text NOT NULL DEFAULT 'draft', -- draft / paid / generating / done / refunded
    upload_ctx       jsonb,                         -- 开题报告等投喂材料的解析结果
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_orders_owner ON writing_orders(tenant_id, owner_id, created_at DESC);  -- R1

-- 大纲版本（免费 N 次由 quota_ledger 控制，服务端 402 拦截）
CREATE TABLE order_outlines (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id    uuid NOT NULL REFERENCES writing_orders(id) ON DELETE CASCADE,
    tenant_id   uuid NOT NULL REFERENCES tenants(id),
    version     int  NOT NULL,
    outline     jsonb NOT NULL,                     -- [{name, wordCount, points:[]}]
    model       text NOT NULL,                      -- 生成用的模型（透明）
    prompt_ver  text NOT NULL,                      -- prompt 版本（可审计）
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (order_id, version)
);

-- 逐章正文。ai_level 是结构性字段：A=AI 生成 / B=AI 辅助 / C=人写，导出不可关（合规标识）
CREATE TABLE order_chapters (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id    uuid NOT NULL REFERENCES writing_orders(id) ON DELETE CASCADE,
    tenant_id   uuid NOT NULL REFERENCES tenants(id),
    idx         int  NOT NULL,
    title       text NOT NULL,
    body_md     text,
    ai_level    text NOT NULL DEFAULT 'B',
    word_count  int  NOT NULL DEFAULT 0,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (order_id, idx)
);

-- 引用条目：每条带溯源证据（修复「百分百真实」的口头承诺 → 机器可验）
CREATE TABLE reference_items (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id    uuid REFERENCES writing_orders(id) ON DELETE CASCADE,
    owner_id    uuid NOT NULL REFERENCES users(id),
    tenant_id   uuid NOT NULL REFERENCES tenants(id),
    kind        text NOT NULL,                      -- journal / book / web / custom
    title       text NOT NULL,
    authors     text,
    year        int,
    doi         text,
    url         text,
    verify_state text NOT NULL DEFAULT 'unverified',-- unverified / verified / suspicious / fake
    verify_evidence jsonb,                          -- 核查证据：命中库、相似度、链接
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_refs_owner ON reference_items(tenant_id, owner_id);

-- ============ 异步任务 ============

CREATE TABLE generation_jobs (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id),
    order_id    uuid REFERENCES writing_orders(id) ON DELETE CASCADE,
    kind        text NOT NULL,                      -- outline / chapter / citation_verify / audit
    status      text NOT NULL DEFAULT 'queued',     -- queued / running / done / failed
    progress    int  NOT NULL DEFAULT 0,
    result      jsonb,
    error       text,
    tokens_in   int  NOT NULL DEFAULT 0,            -- 真实用量，计费依据
    tokens_out  int  NOT NULL DEFAULT 0,
    model       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
CREATE INDEX idx_jobs_order ON generation_jobs(order_id, created_at DESC);

-- ============ 核查报告（复用 review-workflow 规则） ============

CREATE TABLE review_reports (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id    uuid NOT NULL REFERENCES writing_orders(id) ON DELETE CASCADE,
    tenant_id   uuid NOT NULL REFERENCES tenants(id),
    owner_id    uuid NOT NULL REFERENCES users(id),
    verdict     jsonb NOT NULL,                     -- {citation:[], number:[], stats:[]}
    summary     text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ============ 学校模板（格式排版） ============

CREATE TABLE school_templates (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    uuid REFERENCES tenants(id),       -- NULL = 全局模板
    name         text NOT NULL,
    education    text NOT NULL,
    format_spec  jsonb NOT NULL,                    -- 字体/边距/标题层级/参考文献格式
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- ============ 支付 ============

CREATE TABLE payment_orders (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    serial_no     text NOT NULL UNIQUE,             -- 对外流水号
    tenant_id     uuid NOT NULL REFERENCES tenants(id),
    owner_id      uuid NOT NULL REFERENCES users(id),
    order_id      uuid REFERENCES writing_orders(id),
    amount_cents  int  NOT NULL,
    pay_method    text NOT NULL,                    -- wechat / alipay
    status        text NOT NULL DEFAULT 'pending',  -- pending / paid / expired / refunded
    provider_ref  text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    paid_at       timestamptz
);
CREATE INDEX idx_pay_owner ON payment_orders(tenant_id, owner_id);

-- ============ 管理端（R3：独立 RBAC，绝不复用用户 token） ============

CREATE TABLE admin_users (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  uuid REFERENCES tenants(id),         -- NULL = 平台级管理员
    login_name text NOT NULL UNIQUE,
    pass_hash  text NOT NULL,                       -- bcrypt；禁止出现「123456」式初始口令——
                                                -- 初始密码用 openssl rand -hex 12 生成并线下交付
    role       text NOT NULL DEFAULT 'operator',    -- superadmin / tenant_admin / operator
    status     text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE admin_audit_log (                     -- 管理动作全量留痕（原产品无日志）
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    admin_id    uuid NOT NULL REFERENCES admin_users(id),
    action      text NOT NULL,                      -- order.refund / user.ban / tenant.recharge ...
    target      jsonb,
    detail      jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ============ 提现（分销） ============

CREATE TABLE transfer_records (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id),
    user_id     uuid NOT NULL REFERENCES users(id),
    amount_cents int NOT NULL,
    status      text NOT NULL DEFAULT 'pending',    -- pending / approved / rejected / paid
    auditor_id  uuid REFERENCES admin_users(id),
    audited_at  timestamptz,
    note        text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- v1.1 多租户白标 + 分销
-- 纪律：租户渠道密钥（微信/短信等）一律放 tenant_configs 的 *_enc 加密列，
-- 任何 API 只暴露 branding 白名单字段，绝不返回密钥（修复原产品 websiteInfo 泄露洞）。
-- ============================================================
CREATE TABLE IF NOT EXISTS tenants (
    id            VARCHAR(32) PRIMARY KEY,
    name          VARCHAR(64) NOT NULL,
    domain        VARCHAR(255) NOT NULL UNIQUE,
    plan          VARCHAR(16) NOT NULL DEFAULT 'free',
    balance_cents INTEGER NOT NULL DEFAULT 0,
    status        VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tenant_configs (
    tenant_id       VARCHAR(32) PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    brand_color     VARCHAR(7) NOT NULL DEFAULT '#111827',
    logo_url        VARCHAR(255),
    support_contact VARCHAR(128),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS distributors (
    id            VARCHAR(32) PRIMARY KEY,
    tenant_id     VARCHAR(64) NOT NULL DEFAULT 'primary',
    name          VARCHAR(64) NOT NULL,
    phone         VARCHAR(32) NOT NULL,
    code          VARCHAR(32) NOT NULL UNIQUE,
    rate_bps      INTEGER NOT NULL DEFAULT 500,   -- 万分比佣金率，500=5%
    balance_cents INTEGER NOT NULL DEFAULT 0,
    status        VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_distributors_tenant_id ON distributors(tenant_id);

-- 佣金账：只能由「订单支付成功」事件生成，金额=服务端价×rate_bps，客户端不可传
CREATE TABLE IF NOT EXISTS commissions (
    id                 VARCHAR(32) PRIMARY KEY,
    tenant_id          VARCHAR(64) NOT NULL,
    distributor_id     VARCHAR(32) NOT NULL,
    order_id           VARCHAR(32) NOT NULL,
    order_amount_cents INTEGER NOT NULL,
    rate_bps           INTEGER NOT NULL,
    amount_cents       INTEGER NOT NULL,
    status             VARCHAR(16) NOT NULL DEFAULT 'pending',  -- pending→settled
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    settled_at         TIMESTAMPTZ,
    UNIQUE (order_id, distributor_id)                            -- 同一订单只算一次佣金
);
CREATE INDEX IF NOT EXISTS ix_commissions_distributor_id ON commissions(distributor_id);

CREATE TABLE IF NOT EXISTS distributor_transfers (
    id             VARCHAR(32) PRIMARY KEY,
    tenant_id      VARCHAR(64) NOT NULL,
    distributor_id VARCHAR(32) NOT NULL,
    amount_cents   INTEGER NOT NULL,
    status         VARCHAR(16) NOT NULL DEFAULT 'requested',    -- requested→paid/rejected
    note           VARCHAR(200),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_at        TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_distributor_transfers_distributor_id ON distributor_transfers(distributor_id);

ALTER TABLE writing_orders ADD COLUMN IF NOT EXISTS distributor_code VARCHAR(32);
CREATE INDEX IF NOT EXISTS ix_writing_orders_distributor_code ON writing_orders(distributor_code);

-- ============================================================
-- v1.2 短信验证码 + 微信扫码登录会话
-- 纪律：验证码只存 SHA-256 摘要（phone:scene:code）、5 分钟过期、限 5 次尝试；
-- 不对「手机号是否注册」做分支响应（原产品正是靠这个差异泄露注册状态）。
-- ============================================================
CREATE TABLE IF NOT EXISTS sms_codes (
    id         VARCHAR(32) PRIMARY KEY,
    phone      VARCHAR(32) NOT NULL,
    scene      VARCHAR(16) NOT NULL DEFAULT 'register',
    code_hash  VARCHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    consumed   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_sms_codes_phone ON sms_codes(phone);

CREATE TABLE IF NOT EXISTS wechat_scenes (
    id           VARCHAR(32) PRIMARY KEY,
    scene        VARCHAR(64) NOT NULL UNIQUE,
    status       VARCHAR(16) NOT NULL DEFAULT 'pending',
    user_id      VARCHAR(32),
    tenant_id    VARCHAR(64) NOT NULL DEFAULT 'primary',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at TIMESTAMPTZ
);
