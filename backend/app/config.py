"""全局配置：一律从环境变量读取，绝不硬编码密钥（逆向教训：websiteInfo 泄密）。"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 数据库 / Redis
    database_url: str = "postgresql+asyncpg://scholar:scholar@localhost:5432/scholar"
    redis_url: str = "redis://localhost:6379/0"

    # 鉴权：JWT 用非对称思路太重，MVP 用 HS256 + 每次部署随机默认（生产必须显式设置）
    jwt_secret: str = "change-me-in-production"
    jwt_expire_days: int = 7

    # 短信签名密钥（HMAC，5 分钟有效；替代静态盐 sha256）
    sms_hmac_key: str = "change-me-sms"
    # 开发模式：跳过真实短信，验证码固定 000000（生产必须 false）
    sms_dev_mode: bool = True
    sms_provider: str = "dev"          # dev | http（http 走 sms_api_url 网关）
    sms_api_url: str = ""
    sms_api_token: str = ""
    sms_code_ttl_seconds: int = 300
    task_queue: str = "inline"         # inline（asyncio）| arq（Redis 队列，多实例部署用）
    wechat_app_id: str = ""            # 扫码登录（生产需填，空则只有 dev mock 可用）
    wechat_app_secret: str = ""

    # 文献源凭据（可选）：OpenAlex 带 mailto 进「礼貌池」配额更稳；S2 key 提高限额
    openalex_mailto: str = ""
    openalex_api_key: str = ""
    semantic_scholar_api_key: str = ""

    # 免费大纲次数（服务端强制，quota_ledger 台账）
    free_outline_limit: int = 3

    # 启动时自动建表（sqlite 开发/测试便利；生产用 deploy/init.sql，置 false）
    db_auto_create: bool = True

    # LLM Provider（OpenAI 兼容统一入口；本地 vLLM/Ollama 也是这个协议）
    llm_provider: str = "openai_compat"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"

    # 多租户：主域。子域/自定义域通过 tenants 表解析
    primary_domain: str = "localhost:3000"

    # v0.5 支付：mock=确认端点模拟回调（默认，自部署演示）；manual=管理员人工确认收款；
    # 真实微信/支付宝商户回调 v1.0 接 webhook（provider_ref 字段已预留）
    payment_mode: str = "mock"

    # v0.5 管理端：初始管理员（线下交付语义——密码从环境注入，非硬编码；
    # 空则不创建。生产：openssl rand -hex 12 生成后写入环境变量）
    admin_initial_login: str = "admin"
    admin_initial_password: str = ""

    # v1.0 限流（进程内滑动窗口；多实例部署应换 Redis 实现）
    rate_limit_login_per_minute: int = 20
    rate_limit_llm_per_minute: int = 10
    rate_limit_search_per_minute: int = 30

    # CORS 白名单（逗号分隔；默认本地开发地址，生产必须显式收紧）
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    model_config = {"env_file": ".env", "env_prefix": "SC_"}


settings = Settings()
