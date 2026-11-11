"""最小 i18n 层（v1.12 #15）。

范围取舍：不追求把整站文案抽成 PO 文件——那对单仓双语文档产品是过度工程。
真正影响产出的只有两处：
1. 提示词系统消息（决定生成中文还是英文正文）；
2. 少量外发文案（日报邮件、导出免责声明）。

所以这里提供 `SUPPORTED`、`normalize_lang()`、`pick()` 与一份小目录，提示词本身
仍放在 prompts/ 里（离使用点最近），只把「选哪个」的动作集中到本模块。
"""
from __future__ import annotations

SUPPORTED = ("zh", "en")
DEFAULT = "zh"

# 外发/展示文案目录（key → {lang: text}）
_CATALOG: dict[str, dict[str, str]] = {
    "report.subject": {"zh": "Scholar Copilot 运营日报", "en": "Scholar Copilot Daily Report"},
    "report.revenue": {"zh": "营收", "en": "Revenue"},
    "report.orders": {"zh": "新订单", "en": "New orders"},
    "report.users": {"zh": "新用户", "en": "New users"},
    "report.tokens": {"zh": "Token 用量", "en": "Tokens"},
    "export.disclaimer": {
        "zh": "本文档由 AI 辅助生成，作者已对全部内容负责。",
        "en": "This document was produced with AI assistance; the author is responsible for all content.",
    },
    "audit.disclaimer": {
        "zh": "核查结论仅为自动化提示，不替代人工判断。",
        "en": "Automated checks are advisory and do not replace human review.",
    },
}


def normalize_lang(lang: str | None) -> str:
    """把入参收敛到 SUPPORTED；未知/空一律回落到默认中文。"""
    value = (lang or "").strip().lower()
    if value.startswith("zh"):
        return "zh"
    if value.startswith("en"):
        return "en"
    return DEFAULT


def pick(value: str | dict | None, lang: str | None = None) -> str:
    """取文案：value 是 dict 时按语言挑，缺失回落到默认语言再回落到第一项。"""
    if isinstance(value, dict):
        key = normalize_lang(lang)
        if key in value:
            return value[key]
        return value.get(DEFAULT) or next(iter(value.values()), "")
    return value or ""


def t(key: str, lang: str | None = None) -> str:
    """目录取词。未知 key 返回 key 本身（便于发现漏配，而不是静默空串）。"""
    entry = _CATALOG.get(key)
    if entry is None:
        return key
    return pick(entry, lang)


def catalog(lang: str | None = None) -> dict[str, str]:
    """导出整份目录（前端切换语言时一次性拉取）。"""
    return {key: t(key, lang) for key in _CATALOG}
