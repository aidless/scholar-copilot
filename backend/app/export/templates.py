"""学校格式模板库（v1.12 #10）：内置校样例 + 租户自建模板。

原产品的 formatTemplate 是隐藏接口，前端既看不到规则也不能自定义。这里把格式
规则变成**数据**：一条模板 = 一份可直接读的 dict（正文/三级标题/页边距）。

诚实性约束（与原产品的重要差别）：
- 内置模板一律在 label/note 里写「示例」，**不声称是各校官方规范**——各校细则常
  改版，写死成「官方」就是误导；用户需按自己学校的最新要求核对。
- 自建模板与内置模板走同一套 `validate_spec`，缺字段/非法字号直接 422，
  不静默用默认值填空（静默补默认 = 导出结果与用户预期不符且不报错）。
"""
from __future__ import annotations

# 各字段的合法范围（值是「人能读的常量」，不藏在魔法数里）
_SIZE_RANGE = (8, 36)          # 字号 pt
_SPACING_RANGE = (1.0, 3.0)    # 行距倍数
_MARGIN_RANGE = (0.5, 6.0)     # 页边距 cm

_REQUIRED_HEADINGS = ("heading1", "heading2", "heading3")
_PAGE_KEYS = ("top_cm", "bottom_cm", "left_cm", "right_cm")
_BODY_KEYS = ("east", "latin", "size_pt", "line_spacing")


def _check_size(value, where: str) -> None:
    if not isinstance(value, (int, float)) or not (_SIZE_RANGE[0] <= value <= _SIZE_RANGE[1]):
        raise ValueError(f"{where}.size_pt 必须是 {_SIZE_RANGE[0]}~{_SIZE_RANGE[1]} 的数字，得到 {value!r}")


def validate_spec(spec: dict) -> dict:
    """校验一份模板规格；合法则原样返回，非法抛 ValueError（带具体字段名）。

    不做「缺字段就补默认」——那样用户会拿到一份自己没要求的格式却毫无提示。
    """
    if not isinstance(spec, dict):
        raise ValueError("模板规格必须是对象")
    label = spec.get("label")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("模板缺少 label")

    body = spec.get("body")
    if not isinstance(body, dict):
        raise ValueError("模板缺少 body")
    for key in _BODY_KEYS:
        if key not in body:
            raise ValueError(f"body 缺少字段 {key}")
    _check_size(body["size_pt"], "body")
    ls = body["line_spacing"]
    if not isinstance(ls, (int, float)) or not (_SPACING_RANGE[0] <= ls <= _SPACING_RANGE[1]):
        raise ValueError(f"body.line_spacing 必须是 {_SPACING_RANGE[0]}~{_SPACING_RANGE[1]} 的数字")

    for name in _REQUIRED_HEADINGS:
        h = spec.get(name)
        if not isinstance(h, dict):
            raise ValueError(f"模板缺少 {name}")
        if "east" not in h:
            raise ValueError(f"{name} 缺少字段 east")
        _check_size(h.get("size_pt"), name)

    page = spec.get("page")
    if not isinstance(page, dict):
        raise ValueError("模板缺少 page")
    for key in _PAGE_KEYS:
        if key not in page:
            raise ValueError(f"page 缺少字段 {key}")
        v = page[key]
        if not isinstance(v, (int, float)) or not (_MARGIN_RANGE[0] <= v <= _MARGIN_RANGE[1]):
            raise ValueError(f"page.{key} 必须是 {_MARGIN_RANGE[0]}~{_MARGIN_RANGE[1]} cm 的数字")
    return spec


def _spec(label, school, degree, note, *, h1_size, h2_size, h3_size, h2_east="黑体",
          h3_east="宋体", page=(2.54, 2.54, 3.0, 2.5), body_size=12, indent=24):
    return {
        "label": label, "school": school, "degree": degree, "note": note,
        "body": {"east": "宋体", "latin": "Times New Roman", "size_pt": body_size,
                 "line_spacing": 1.5, "first_line_indent_pt": indent},
        "heading1": {"east": "黑体", "size_pt": h1_size, "bold": True, "center": True},
        "heading2": {"east": h2_east, "size_pt": h2_size, "bold": True, "center": False},
        "heading3": {"east": h3_east, "size_pt": h3_size, "bold": True, "center": False},
        "page": {"top_cm": page[0], "bottom_cm": page[1],
                 "left_cm": page[2], "right_cm": page[3]},
    }


# 内置「示例」模板：数值来自各校公开规范中**最常见**的组合，但不声称官方
BUILTIN_TEMPLATES: dict[str, dict] = {
    "示例-清华-硕士": _spec(
        "清华硕士（示例）：章标题黑体三号居中，正文宋体小四 1.5 倍行距，左侧装订 3cm",
        "清华大学", "硕士", "示例模板，数值取自公开规范的常见组合，请以本校最新研究生院规定为准",
        h1_size=16, h2_size=14, h3_size=12, page=(2.54, 2.54, 3.0, 2.5)),
    "示例-北大-博士": _spec(
        "北大博士（示例）：章标题黑体二号居中，节标题黑体四号，页边距上 3cm",
        "北京大学", "博士", "示例模板，非学校官方发布；博士论文格式各院系另有细则",
        h1_size=22, h2_size=14, h3_size=13, page=(3.0, 2.5, 3.0, 2.5)),
    "示例-浙大-本科": _spec(
        "浙大本科（示例）：章标题黑体三号居中，正文宋体小四 1.5 倍行距",
        "浙江大学", "本科", "示例模板，请以本校教务处最新毕业论文格式要求为准",
        h1_size=16, h2_size=14, h3_size=12, h2_east="黑体", h3_east="宋体",
        page=(2.54, 2.54, 3.0, 2.5)),
    "示例-通用-期刊投稿": _spec(
        "期刊投稿（示例）：章标题黑体四号左对齐，正文宋体五号，窄页边距",
        "通用", "期刊", "示例模板，不同期刊差异极大，投稿前请按目标期刊 author guidelines 调整",
        h1_size=14, h2_size=12, h3_size=10.5, page=(2.0, 2.0, 2.0, 2.0),
        body_size=10.5, indent=21),
}


def builtin_profiles() -> dict[str, dict]:
    """内置模板 + 通用 4 档案 合并成一张表（导出按 key 解析时共用）。"""
    from .formatter import FORMAT_PROFILES

    out: dict[str, dict] = {}
    for key, spec in FORMAT_PROFILES.items():
        out[key] = {**spec, "builtin": True}
    for key, spec in BUILTIN_TEMPLATES.items():
        out[key] = {**spec, "builtin": True}
    return out
