"""v1.12 #10：学校格式模板库——内置校样例 + 租户自建模板 + 导出可用。

原产品 formatTemplate 是隐藏接口，前端拿不到规则、也不能自定义。这里：
- 内置若干高校「示例」模板（显式标注非官方，需自行核对）；
- 租户可自建模板（管理端 CRUD），字段校验严格（缺字段/字号非法即 422）；
- 导出按 key 解析，内置与自建同一套解析器，不黑箱。
"""
import pytest
from fastapi.testclient import TestClient

PHONE_A = "13800000041"
PHONE_B = "13800000042"
PW = "Test123456"
ADMIN_PW = "t3st-Adm1n-Pw!"

GOOD_SPEC = {
    "label": "某校硕士示例",
    "body": {"east": "宋体", "latin": "Times New Roman", "size_pt": 12,
             "line_spacing": 1.5, "first_line_indent_pt": 24},
    "heading1": {"east": "黑体", "size_pt": 16, "bold": True, "center": True},
    "heading2": {"east": "黑体", "size_pt": 14, "bold": True, "center": False},
    "heading3": {"east": "宋体", "size_pt": 12, "bold": True, "center": False},
    "page": {"top_cm": 2.5, "bottom_cm": 2.5, "left_cm": 3.0, "right_cm": 2.5},
}


def make_client():
    from app.main import create_app
    return TestClient(create_app())


def register(client, phone):
    r = client.post("/auth/register",
                    json={"phone": phone, "password": PW, "check_code": "000000"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def admin_token(client):
    r = client.post("/admin/login", json={"username": "admin", "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def full_order(client, token):
    order = client.post("/writing/orders",
                        json={"title": "模板库测试论文", "education": "硕士", "word_count": 8000},
                        headers=auth(token)).json()
    client.post(f"/writing/orders/{order['id']}/outline?wait=true", json={}, headers=auth(token))
    r = client.post(f"/payments/orders/{order['id']}", json={"pay_method": "alipay"},
                    headers=auth(token))
    client.post(f"/payments/{r.json()['serial_no']}/confirm", headers=auth(token))
    for node in ["ch1", "ch2", "ch3", "ch4", "ch5"]:
        client.post(f"/writing/orders/{order['id']}/chapters/{node}?wait=true",
                    json=None, headers=auth(token))
    return order["id"]


# ── 纯函数层 ────────────────────────────────────────────────

def test_builtin_school_templates_are_valid_and_labeled():
    from app.export.templates import BUILTIN_TEMPLATES, validate_spec

    assert len(BUILTIN_TEMPLATES) >= 4
    for key, spec in BUILTIN_TEMPLATES.items():
        validate_spec(spec)  # 不抛即合法
        # 每个内置模板必须写明「示例、非官方」，避免被当成学校官方规范
        assert "示例" in spec["label"] or "示例" in spec.get("note", ""), key
        assert spec.get("school"), key


def test_validate_spec_rejects_bad_values():
    from app.export.templates import validate_spec

    with pytest.raises(ValueError):
        validate_spec({**GOOD_SPEC, "body": {**GOOD_SPEC["body"], "size_pt": 0}})
    with pytest.raises(ValueError):
        validate_spec({**GOOD_SPEC, "heading1": {"east": "黑体", "size_pt": 99}})
    with pytest.raises(ValueError):
        validate_spec({**GOOD_SPEC, "heading1": {"size_pt": 16}})  # 缺 east
    bad_page = {k: v for k, v in GOOD_SPEC["page"].items() if k != "left_cm"}
    with pytest.raises(ValueError):
        validate_spec({**GOOD_SPEC, "page": bad_page})


# ── 管理端 CRUD ─────────────────────────────────────────────

def test_admin_creates_template_and_it_appears_in_profiles():
    with make_client() as client:
        at = admin_token(client)
        r = client.post("/admin/format-templates", headers=auth(at), json={
            "key": "某校-硕士-示例", "name": "某校硕士（示例）",
            "school": "某校", "degree": "硕士", "spec": GOOD_SPEC})
        assert r.status_code == 201, r.text
        tid = r.json()["id"]

        profiles = client.get("/formatting/profiles").json()
        keys = {p["key"] for p in profiles}
        assert "某校-硕士-示例" in keys
        hit = next(p for p in profiles if p["key"] == "某校-硕士-示例")
        assert hit["school"] == "某校"
        assert hit["builtin"] is False

        # 内置模板也带 school/builtin 标记
        builtin = next(p for p in profiles if p["builtin"] is True)
        assert builtin["school"]

        # 重名冲突 409
        r2 = client.post("/admin/format-templates", headers=auth(at), json={
            "key": "某校-硕士-示例", "name": "重复", "school": "某校",
            "degree": "硕士", "spec": GOOD_SPEC})
        assert r2.status_code == 409

        # 删除
        assert client.delete(f"/admin/format-templates/{tid}",
                             headers=auth(at)).status_code == 204
        keys2 = {p["key"] for p in client.get("/formatting/profiles").json()}
        assert "某校-硕士-示例" not in keys2


def test_admin_template_rejects_invalid_spec():
    with make_client() as client:
        at = admin_token(client)
        r = client.post("/admin/format-templates", headers=auth(at), json={
            "key": "坏模板", "name": "坏", "school": "X", "degree": "硕士",
            "spec": {**GOOD_SPEC, "page": {}}})
        assert r.status_code == 422, r.text


def test_admin_templates_requires_admin_role():
    with make_client() as client:
        token = register(client, PHONE_B)
        r = client.post("/admin/format-templates", headers=auth(token), json={
            "key": "越权", "name": "越权", "school": "X", "degree": "本科",
            "spec": GOOD_SPEC})
        assert r.status_code == 403


# ── 导出按模板 key 生效 ─────────────────────────────────────

def test_export_with_admin_template():
    with make_client() as client:
        at = admin_token(client)
        client.post("/admin/format-templates", headers=auth(at), json={
            "key": "某校-硕士-示例", "name": "某校硕士（示例）",
            "school": "某校", "degree": "硕士", "spec": GOOD_SPEC})

        token = register(client, PHONE_A)
        order_id = full_order(client, token)
        r = client.post(f"/writing/orders/{order_id}/export?profile=某校-硕士-示例",
                        headers=auth(token))
        assert r.status_code == 200, r.text
        assert r.content[:2] == b"PK"

        # 未知 key 仍 422 且提示去看 profiles
        r2 = client.post(f"/writing/orders/{order_id}/export?profile=不存在模板",
                         headers=auth(token))
        assert r2.status_code == 422
        assert "formatting/profiles" in r2.json()["detail"]


def test_export_with_builtin_school_template():
    with make_client() as client:
        from app.export.templates import BUILTIN_TEMPLATES

        key = next(iter(BUILTIN_TEMPLATES))
        token = register(client, PHONE_A)
        order_id = full_order(client, token)
        r = client.post(f"/writing/orders/{order_id}/export?profile={key}", headers=auth(token))
        assert r.status_code == 200, r.text
        assert r.content[:2] == b"PK"
