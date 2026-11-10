"""启动自检：把「配置看起来能跑、实际跑不通」的情况在启动时就喊出来。

为什么需要：clone 下来直接 `docker compose up -d` 是最常见的第一次接触方式。
如果 `SC_LLM_API_KEY` 没填，服务能起来、页面能开、下单也能成，**直到第一次生成
才失败**，报的还是上游 401 —— 用户会以为是代码坏了。这类「延迟暴露的配置错误」
必须在启动日志里说清楚。

这里只产生**警告**，不阻断启动（演示模式、自建网关无密钥等合法场景要能跑）。
"""
from .config import Settings

# 判定「演示/无密钥」用的哨兵值。**统一小写比对**——调用方已 .lower()，
# 这里若留大写（原版写 "TODO"）会漏检：实测 test_placeholder_llm_key_warns 变红。
_PLACEHOLDER_KEYS = {"", "sk-xxx", "your-api-key", "changeme", "todo", "none", "null"}


def startup_warnings(s: Settings) -> list[str]:
    """返回启动警告列表（空列表 = 没发现问题）。纯函数，便于测试。"""
    out: list[str] = []

    if s.llm_provider == "fake":
        out.append(
            "LLM 使用 fake provider（内置假数据），生成内容不是真实模型输出——仅供演示/测试。"
        )
    elif s.llm_provider == "openai_compat":
        if s.llm_api_key.strip().lower() in _PLACEHOLDER_KEYS:
            out.append(
                f"SC_LLM_API_KEY 未设置：{s.llm_base_url} 的生成请求会失败。"
                "要么填上真实密钥，要么设 SC_LLM_PROVIDER=fake 走演示模式。"
            )

    if s.sms_dev_mode:
        out.append(
            "SC_SMS_DEV_MODE=true：任意手机号用验证码 000000 即可注册/登录，"
            "且 /auth/wechat/mock-approve 可用——**只能用于本地演示，生产必须关闭**。"
        )
    elif s.sms_provider == "dev":
        out.append(
            "SC_SMS_PROVIDER=dev：验证码只写日志不真发短信，生产环境用户收不到码。"
        )

    if s.payment_mode == "mock":
        out.append("SC_PAYMENT_MODE=mock：支付确认不校验真实渠道回调，生产必须改为真实渠道。")

    if not s.admin_initial_password:
        out.append(
            "SC_ADMIN_INITIAL_PASSWORD 为空：不会创建初始管理员，/admin/* 无法登录。"
            "首次部署请设置后再启动（建好后可从环境变量移除）。"
        )

    if s.jwt_secret in ("", "change-me", "dev-secret", "test-secret"):
        out.append("SC_JWT_SECRET 仍是默认/测试值：任何人都能伪造登录 token，必须换成随机长串。")

    if s.db_auto_create and s.database_url.startswith("postgresql"):
        out.append(
            "SC_DB_AUTO_CREATE=true 且数据库是 Postgres：create_all 与 alembic 会形成双真相源，"
            "建议改用 alembic upgrade head 建表并把此项设为 false。"
        )

    if s.rate_limit_backend == "memory" and s.task_queue == "arq":
        out.append(
            "SC_RATE_LIMIT_BACKEND=memory 但已启用 arq 多进程：限流配额会按进程数放大，建议改 redis。"
        )

    return out
