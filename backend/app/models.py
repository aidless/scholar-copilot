"""SQLAlchemy 模型（v0.2 子集，列名与 deploy/init.sql 对齐）。

纪律（THREAT-MODEL R1）：所有用户资源表带 tenant_id + owner_id 双列，
查询必须过 app/tenancy.ownership_filter，禁止裸查。
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, JSON, String, Text

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
