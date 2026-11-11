"""v1.12 #15：i18n —— 提示词按语言切换、文案目录可取。

只测真正影响产出的两件事：
1. 订单语言为 en 时，送给模型的是英文系统提示（不是中文）；
2. 文案目录对未知语言回落中文，对未知 key 返回 key 本身（漏配能被看见）。
"""
import pytest

from app.i18n import DEFAULT, SUPPORTED, catalog, normalize_lang, pick, t
from app.prompts.chapter_prompts import (CHAPTER_SYSTEM_PROMPT,
                                        CHAPTER_SYSTEM_PROMPT_EN,
                                        chapter_system_prompt)
from app.prompts.outline_prompts import (OUTLINE_SYSTEM_PROMPT,
                                         OUTLINE_SYSTEM_PROMPT_EN,
                                         outline_system_prompt)


def test_supported_languages():
    assert "zh" in SUPPORTED and "en" in SUPPORTED
    assert DEFAULT == "zh"


@pytest.mark.parametrize("raw,expected", [
    ("en", "en"), ("EN", "en"), ("en-US", "en"), ("英文", "zh"),
    ("zh", "zh"), ("zh-CN", "zh"), ("", "zh"), (None, "zh"),
])
def test_normalize_lang(raw, expected):
    assert normalize_lang(raw) == expected


def test_outline_system_prompt_switches_language():
    zh = outline_system_prompt("zh")
    en = outline_system_prompt("en")
    assert zh == OUTLINE_SYSTEM_PROMPT
    assert en == OUTLINE_SYSTEM_PROMPT_EN
    assert zh != en
    # 英文提示必须真的是英文指令（否则「切语言」是假的）
    assert "outline" in en.lower()
    assert "大纲" in zh


def test_chapter_system_prompt_switches_language():
    assert chapter_system_prompt("en") == CHAPTER_SYSTEM_PROMPT_EN
    assert chapter_system_prompt("zh") == CHAPTER_SYSTEM_PROMPT
    assert "academic" in chapter_system_prompt("en").lower()


def test_unknown_language_falls_back_to_default():
    assert outline_system_prompt("jp") == OUTLINE_SYSTEM_PROMPT
    assert chapter_system_prompt("") == CHAPTER_SYSTEM_PROMPT


def test_catalog_message_and_fallback():
    assert t("report.subject", "en") == "Scholar Copilot Daily Report"
    assert t("report.subject", "zh").startswith("Scholar Copilot")
    assert t("report.subject", "fr") == t("report.subject", DEFAULT)
    # 未知 key 原样返回，便于发现漏配
    assert t("no.such.key", "en") == "no.such.key"


def test_catalog_export_shape():
    zh = catalog("zh")
    en = catalog("en")
    assert set(zh) == set(en)
    assert all(isinstance(v, str) and v for v in zh.values())
    assert zh["export.disclaimer"] != en["export.disclaimer"]


def test_pick_accepts_plain_string():
    assert pick("纯字符串", "en") == "纯字符串"
    assert pick({"zh": "中", "en": "EN"}, "en") == "EN"
    assert pick({"zh": "中"}, "en") == "中"
