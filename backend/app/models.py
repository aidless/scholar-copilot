"""SQLAlchemy 模型（v0.2 子集，列名与 deploy/init.sql 对齐）。

纪律（THREAT-MODEL R1）：所有用户资源表带 tenant_id + owner_id 双列，
查询必须过 app/tenancy.ownership_filter，禁止裸查。
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, JSON, String, Text

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False, default="primary", index=True)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)
    # 微信 openid（扫码登录后绑定；绑定后再次扫码可免密登录）
    wechat_openid = Column(String(64), unique=True, index=True)
    created_at = Column(DateTime(timezone=True), default=_now)


class WritingOrder(Base):
    """写作订单。status: draft→outlining→outline_done→writing→writing_done→exported"""

    __tablename__ = "writing_orders"

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    owner_id = Column(String(32), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    education = Column(String(16), nullable=False)  # 本科/硕士/博士
    word_count = Column(Integer, nullable=False)
    language = Column(String(8), nullable=False, default="zh")
    writing_type = Column(String(32), nullable=False, default="thesis")
    status = Column(String(32), nullable=False, default="draft")
    price_cents = Column(Integer, nullable=False, default=0)
    distributor_code = Column(String(32), index=True)  # 推广码（订单成交后给代理计佣）  # 服务端算，前端传入无效
    paid_at = Column(DateTime(timezone=True))  # v0.5：支付成功时间；正文生成/改写需已支付（对照原产品付费流）
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (
        Index("ix_orders_tenant_owner", "tenant_id", "owner_id"),
    )


class OrderOutline(Base):
    """大纲版本表：每次生成追加一行，version 递增。"""

    __tablename__ = "order_outlines"

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False)
    order_id = Column(String(32), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    content_md = Column(Text, nullable=False)
    tree_json = Column(JSON, nullable=False)  # outline_parser 的树结构
    created_at = Column(DateTime(timezone=True), default=_now)


class OrderChapter(Base):
    """章节骨架行：outline 成功时按 level1 节点创建。
    status: pending→writing→done / failed
    ai_level: A=AI生成未修改 B=AI初稿已修改 C=人工撰写（不可关，导出必带）
    """

    __tablename__ = "order_chapters"

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False)
    order_id = Column(String(32), nullable=False, index=True)
    node_id = Column(String(32), nullable=False)  # ch1 / ch1_sec2 / ch1_sec2_sub3
    idx = Column(Integer, nullable=False)  # 章序，导出按此排序
    level = Column(Integer, nullable=False, default=1)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(String(16), nullable=False, default="pending")
    content_md = Column(Text)
    word_count = Column(Integer, nullable=False, default=0)
    ai_level = Column(String(1), nullable=False, default="C")
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (
        Index("ix_chapters_order_node", "order_id", "node_id", unique=True),
    )


class GenerationJob(Base):
    """异步任务（大纲/章节）。v0.2 用 asyncio 内联执行，v0.5 换 arq。"""

    __tablename__ = "generation_jobs"

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False)
    order_id = Column(String(32), nullable=False, index=True)
    kind = Column(String(16), nullable=False)  # outline / chapter
    node_id = Column(String(32))  # kind=chapter 时目标节点
    status = Column(String(16), nullable=False, default="queued")  # queued/running/done/failed
    progress = Column(Integer, nullable=False, default=0)
    result_json = Column(JSON)
    error = Column(Text)
    tokens_in = Column(Integer, nullable=False, default=0)
    tokens_out = Column(Integer, nullable=False, default=0)
    model = Column(String(64))
    created_at = Column(DateTime(timezone=True), default=_now)
    finished_at = Column(DateTime(timezone=True))


class QuotaLedger(Base):
    """append-only 配额台账，两类行：
    - 消费/冲正（is_usage=True）：大纲生成 +1、失败退款 -1，净额=已用；
    - 赠送/回收（is_usage=False）：管理员调整，净额=额外配额。
    余额 = limit - Σ(is_usage) + Σ(非 is_usage)。
    """

    __tablename__ = "quota_ledger"

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False)
    user_id = Column(String(32), nullable=False, index=True)
    kind = Column(String(32), nullable=False)  # outline
    delta = Column(Integer, nullable=False)
    is_usage = Column(Boolean, nullable=False, default=True)
    reason = Column(String(255), nullable=False)
    order_id = Column(String(32))
    created_at = Column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ix_quota_user_kind", "user_id", "kind"),
    )


class ReferenceItem(Base):
    """订单文献引用。verify_state: unverified / verified / suspicious / fake（v0.4 核查填充）。"""

    __tablename__ = "reference_items"

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False)
    owner_id = Column(String(32), nullable=False)
    order_id = Column(String(32), nullable=False, index=True)
    kind = Column(String(16), nullable=False, default="journal")  # journal/book/web/custom
    title = Column(String(500), nullable=False)
    authors = Column(String(1000))
    year = Column(Integer)
    doi = Column(String(255))
    url = Column(String(500))
    cited_by = Column(Integer, default=0)
    verify_state = Column(String(16), nullable=False, default="unverified")
    verify_evidence = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=_now)


class PaymentOrder(Base):
    """支付单：订单付费流水。status: pending→paid / expired / refunded。
    开源纪律：默认 mock 网关（确认端点模拟回调）；接真实微信/支付宝商户
    需自部署配置 webhook，字段 provider_ref 预留三方流水号。
    """

    __tablename__ = "payment_orders"

    id = Column(String(32), primary_key=True, default=_uuid)
    serial_no = Column(String(64), nullable=False, unique=True)  # 对外流水号
    tenant_id = Column(String(64), nullable=False, index=True)
    owner_id = Column(String(32), nullable=False, index=True)
    order_id = Column(String(32), nullable=False, index=True)
    amount_cents = Column(Integer, nullable=False)  # 从订单服务端价取，禁止客户端传
    pay_method = Column(String(16), nullable=False)  # wechat / alipay
    status = Column(String(16), nullable=False, default="pending")
    provider_ref = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=_now)
    paid_at = Column(DateTime(timezone=True))


class AdminUser(Base):
    """管理端账号（修复原产品洞 P1-1：匿名 Vue 管理台 + 弱口令）。
    初始管理员经 SC_ADMIN_INITIAL_PASSWORD 环境变量创建（线下交付语义）；
    role: superadmin / tenant_admin / operator。
    """

    __tablename__ = "admin_users"

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64))  # NULL = 平台级
    login_name = Column(String(64), nullable=False, unique=True)
    pass_hash = Column(String(128), nullable=False)
    role = Column(String(16), nullable=False, default="operator")
    status = Column(String(16), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), default=_now)


class AdminAuditLog(Base):
    """管理动作全量留痕（原产品无日志）。"""

    __tablename__ = "admin_audit_log"

    id = Column(String(32), primary_key=True, default=_uuid)
    admin_id = Column(String(32), nullable=False, index=True)
    action = Column(String(64), nullable=False)  # payment.confirm / quota.adjust / ...
    target = Column(JSON)
    detail = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=_now)


class Tenant(Base):
    """白标租户：域名 → 租户路由（原产品靠 websiteInfo 明文吐配置，这里只暴露 branding）。"""

    __tablename__ = "tenants"

    id = Column(String(32), primary_key=True, default=_uuid)
    name = Column(String(128), nullable=False)
    domain = Column(String(255), nullable=False, unique=True)  # 含端口，可含子域
    plan = Column(String(16), nullable=False, default="free")
    balance_cents = Column(Integer, nullable=False, default=0)
    status = Column(String(16), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), default=_now)


class TenantConfig(Base):
    """租户品牌/渠道配置。密钥类字段一律不进本表（加密列在 DB 侧由 DBA 管理）。

    THREAT-MODEL 规则 3：任何对外 API 只能返回 branding 字段。
    """

    __tablename__ = "tenant_configs"

    tenant_id = Column(String(32), primary_key=True)
    brand_color = Column(String(16), nullable=False, default="#111827")
    logo_url = Column(String(255))
    support_contact = Column(String(128))
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


class UsageRecord(Base):
    """token 级用量记录（v1.12 #18）：每次 LLM 调用落一条，append-only。

    cost_cents 按 llm.router.COST_TABLE 折算（元→分四舍五入），fake-model 为 0。
    """

    __tablename__ = "usage_records"
    __table_args__ = (
        Index("ix_usage_records_owner_created", "owner_id", "created_at"),
        Index("ix_usage_records_order_id", "order_id"),
    )

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    owner_id = Column(String(32), nullable=False, index=True)
    order_id = Column(String(32))
    job_id = Column(String(32))
    kind = Column(String(32), nullable=False)  # outline/chapter/rewrite/abstract/ppt/diagram
    model = Column(String(128), nullable=False, default="")
    tokens_in = Column(Integer, nullable=False, default=0)
    tokens_out = Column(Integer, nullable=False, default=0)
    cost_cents = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=_now)


class Account(Base):
    """用户余额/套餐账户（v1.12 #18）。

    tokens_used 是当期累计用量，period_start 起算；订阅不重置用量，
    只把 token_quota 换成新套餐的额度（避免反复订阅刷额度——订阅要花钱）。
    """

    __tablename__ = "accounts"
    __table_args__ = (
        Index("ix_accounts_tenant_owner", "tenant_id", "owner_id"),
    )

    owner_id = Column(String(32), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    plan_key = Column(String(32), nullable=False, default="free")
    balance_cents = Column(Integer, nullable=False, default=0)
    token_quota = Column(Integer, nullable=False, default=0)
    tokens_used = Column(Integer, nullable=False, default=0)
    period_start = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


class AccountLedger(Base):
    """账户流水（append-only）：topup / subscribe / redeem / refund。"""

    __tablename__ = "account_ledger"

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    owner_id = Column(String(32), nullable=False, index=True)
    kind = Column(String(32), nullable=False)
    delta_cents = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    reason = Column(String(255), nullable=False, default="")
    created_at = Column(DateTime(timezone=True), default=_now)


class FormatTemplate(Base):
    """租户自建格式模板（v1.12 #10）。内置模板在代码里，这里只存用户建的。

    spec_json 存完整规格（body/heading1-3/page），由 export.templates.validate_spec 校验后落库。
    key 在租户内唯一——同一租户不能有两条同名模板，否则导出解析会有歧义。
    """

    __tablename__ = "format_templates"
    __table_args__ = (
        Index("ix_format_templates_tenant_key", "tenant_id", "key", unique=True),
    )

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    key = Column(String(64), nullable=False)
    name = Column(String(128), nullable=False)
    school = Column(String(128), nullable=False, default="")
    degree = Column(String(32), nullable=False, default="")
    spec_json = Column(JSON, nullable=False)
    builtin = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=_now)


class Distributor(Base):
    """分销代理：校园代理/渠道商，佣金按 rate_bps 计（万分比，默认 5%）。"""

    __tablename__ = "distributors"

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    phone = Column(String(32), nullable=False)
    code = Column(String(32), nullable=False, unique=True)  # 推广码
    rate_bps = Column(Integer, nullable=False, default=500)
    balance_cents = Column(Integer, nullable=False, default=0)
    status = Column(String(16), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), default=_now)


class Commission(Base):
    """佣金流水：订单支付成功时按服务端价 × rate_bps 生成（pending → settled）。"""

    __tablename__ = "commissions"

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    distributor_id = Column(String(32), nullable=False, index=True)
    order_id = Column(String(32), nullable=False, index=True)
    order_amount_cents = Column(Integer, nullable=False)
    rate_bps = Column(Integer, nullable=False)
    amount_cents = Column(Integer, nullable=False)  # 佣金 = order_amount × rate_bps // 10000
    status = Column(String(16), nullable=False, default="pending")  # pending/settled/cancelled
    created_at = Column(DateTime(timezone=True), default=_now)
    settled_at = Column(DateTime(timezone=True))


class DistributorTransfer(Base):
    """代理提现申请：管理端审核后打款（audit 留痕）。"""

    __tablename__ = "distributor_transfers"

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    distributor_id = Column(String(32), nullable=False, index=True)
    amount_cents = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default="requested")  # requested/paid/rejected
    note = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=_now)
    paid_at = Column(DateTime(timezone=True))


class SmsCode(Base):
    """短信验证码（哈希存储 + 过期时间 + 尝试次数），替代静态盐方案。

    原产品 sign = sha256("saas-sign-" + phone) 是固定盐，任何人可离线复算；
    这里每次发送随机 6 位码、只存 SHA-256 摘要、5 分钟过期、最多试 5 次。
    """

    __tablename__ = "sms_codes"

    id = Column(String(32), primary_key=True, default=_uuid)
    phone = Column(String(32), nullable=False, index=True)
    scene = Column(String(16), nullable=False, default="register")  # register/login
    code_hash = Column(String(64), nullable=False)                   # sha256(phone:scene:code)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    consumed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=_now)


class WechatScene(Base):
    """微信扫码登录会话（scene → 已确认用户）。dev 模式可 mock 确认，生产走真实回调。"""

    __tablename__ = "wechat_scenes"

    id = Column(String(32), primary_key=True, default=_uuid)
    scene = Column(String(64), nullable=False, unique=True, index=True)
    status = Column(String(16), nullable=False, default="pending")  # pending/confirmed/expired
    user_id = Column(String(32))
    # 扫码来源的 openid（微信回调事件里带；用于首次绑定 wechat_openid）
    openid = Column(String(64), index=True)
    tenant_id = Column(String(64), nullable=False, default="primary")
    created_at = Column(DateTime(timezone=True), default=_now)
    confirmed_at = Column(DateTime(timezone=True))


class UploadedFile(Base):
    """用户上传文件（开题报告/降重稿/排版模板等）。

    内容落对象存储（见 app/storage.py），本表只存元数据 + storage_key。
    tenant_id + owner_id 双列，访问须过 ownership_filter（IDOR 纪律同其他资源）。
    """

    __tablename__ = "uploaded_files"

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    owner_id = Column(String(32), nullable=False, index=True)
    order_id = Column(String(32), index=True)  # 可空：不绑定具体订单的临时上传
    kind = Column(String(32), nullable=False, default="attachment")  # 用途分类
    filename = Column(String(255), nullable=False)
    content_type = Column(String(128), nullable=False, default="")
    size = Column(Integer, nullable=False, default=0)
    storage_key = Column(String(255), nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_now)


class GenerationProvenance(Base):
    """内容指纹链（append-only）：AI 参与度 A/B/C 的可审计凭据。

    每次生成/改写记一行：内容 sha256（空白不敏感）+ 当时声明的 ai_level +
    与上一版的相似度（sim_to_prev）。链只追加不改写——与 quota_ledger 同纪律。
    """

    __tablename__ = "generation_provenance"

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    order_id = Column(String(32), nullable=False, index=True)
    node_id = Column(String(32), nullable=False, index=True)
    kind = Column(String(16), nullable=False)  # generate / rewrite / edit
    content_sha256 = Column(String(64), nullable=False, index=True)
    word_count = Column(Integer, nullable=False, default=0)
    ai_level = Column(String(1), nullable=False)
    sim_to_prev = Column(Float)  # 与上一版的相似度（0~1），第一版为空
    job_id = Column(String(32), index=True)
    actor = Column(String(64))  # 谁做的（user id / "system"）
    created_at = Column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ix_prov_order_node", "order_id", "node_id"),
    )


class RedeemCode(Base):
    """兑换码（v1.12 #17）：一码一用，兑换成账户余额。

    code 直接做主键——兑换时按 code 点查，避免扫描；used_by 为空表示未用。
    """

    __tablename__ = "redeem_codes"

    code = Column(String(32), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    batch = Column(String(64), nullable=False, default="", index=True)
    amount_cents = Column(Integer, nullable=False)
    used_by = Column(String(32), index=True)
    used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=_now)


class GroupBuy(Base):
    """拼团（v1.12 #17）：凑满 required 人按 group_price_cents 结算。"""

    __tablename__ = "group_buys"

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    plan_key = Column(String(32), nullable=False)
    required = Column(Integer, nullable=False, default=3)
    joined = Column(Integer, nullable=False, default=0)
    group_price_cents = Column(Integer, nullable=False)
    initiator_id = Column(String(32), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="open")  # open/settled/expired
    expires_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=_now)


class GroupBuyMember(Base):
    """拼团成员（一人一单，重复参团在业务层挡 409）。"""

    __tablename__ = "group_buy_members"
    __table_args__ = (
        Index("ix_group_buy_members_gb_owner", "group_buy_id", "owner_id", unique=True),
    )

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    group_buy_id = Column(String(32), nullable=False, index=True)
    owner_id = Column(String(32), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_now)


class LocalReference(Base):
    """本地文献库条目（v1.12 #21）：离线模式下的检索/核查数据源。

    按 (owner_id, title, year) 去重——同一用户重复导入同一个 BibTeX 不应产生重复条目。
    """

    __tablename__ = "local_references"
    __table_args__ = (
        Index("ix_local_refs_owner_title", "owner_id", "title"),
    )

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    owner_id = Column(String(32), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    authors_json = Column(JSON, default=list)
    year = Column(Integer)
    venue = Column(String(255), nullable=False, default="")
    doi = Column(String(255))
    abstract = Column(Text, nullable=False, default="")
    kind = Column(String(16), nullable=False, default="journal")
    created_at = Column(DateTime(timezone=True), default=_now)


class ExportArtifact(Base):
    """导出产物归档（v1.12 #14）：每次导出落一份，可换签名 URL 再取。"""

    __tablename__ = "export_artifacts"
    __table_args__ = (
        Index("ix_export_artifacts_order_created", "order_id", "created_at"),
    )

    id = Column(String(32), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    owner_id = Column(String(32), nullable=False, index=True)
    order_id = Column(String(32), nullable=False)
    fmt = Column(String(16), nullable=False)
    filename = Column(String(255), nullable=False)
    storage_key = Column(String(512), nullable=False)
    size = Column(Integer, nullable=False, default=0)
    sha256 = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime(timezone=True), default=_now)
