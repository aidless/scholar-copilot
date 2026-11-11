"""v1.8 #6：摘要生成（中/英）+ 前置校验。

fake provider 对非大纲 prompt 返回固定章节正文；摘要端点要求至少一个已完成章节。
"""
from fastapi.testclient import TestClient

PHONE = "13800000011"
PW = "Test123456"


def make_client():
    from app.main import create_app
    return TestClient(create_app())


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def register(client):
    r = client.post("/auth/register",
                    json={"phone": PHONE, "password": PW, "check_code": "000000"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def new_order(client, token):
    r = client.post("/writing/orders",
                    json={"title": "摘要生成测试", "education": "硕士", "word_count": 6000},
                    headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def outline(client, token, oid):
    r = client.post(f"/writing/orders/{oid}/outline?wait=true", json=None,
                    headers=auth(token))
    assert r.status_code == 200, r.text


def pay(client, token, oid):
    r = client.post(f"/payments/orders/{oid}", json={"pay_method": "alipay"},
                    headers=auth(token))
    assert r.status_code == 200, r.text
    serial = r.json()["serial_no"]
    r = client.post(f"/payments/{serial}/confirm", headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["order_paid"] is True


def gen_one_chapter(client, token, oid):
    chs = client.get(f"/writing/orders/{oid}/chapters", headers=auth(token)).json()
    node = chs[0]["node_id"]
    r = client.post(f"/writing/orders/{oid}/chapters/{node}?wait=true", headers=auth(token))
    assert r.status_code == 200, r.text
    return node


def test_abstract_no_done_chapter_409():
    client = make_client()
    token = register(client)
    oid = new_order(client, token)
    outline(client, token, oid)
    r = client.post(f"/writing/orders/{oid}/abstract?lang=zh", headers=auth(token))
    assert r.status_code == 409


def test_abstract_zh_after_chapter():
    client = make_client()
    token = register(client)
    oid = new_order(client, token)
    outline(client, token, oid)
    pay(client, token, oid)
    gen_one_chapter(client, token, oid)
    r = client.post(f"/writing/orders/{oid}/abstract?lang=zh", headers=auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["lang"] == "zh"
    assert data["abstract"].strip()
    assert data["model"]  # fake-model
    assert data["tokens_out"] > 0


def test_abstract_en():
    client = make_client()
    token = register(client)
    oid = new_order(client, token)
    outline(client, token, oid)
    pay(client, token, oid)
    gen_one_chapter(client, token, oid)
    r = client.post(f"/writing/orders/{oid}/abstract?lang=en", headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["lang"] == "en"


def test_abstract_invalid_lang_422():
    client = make_client()
    token = register(client)
    oid = new_order(client, token)
    outline(client, token, oid)
    r = client.post(f"/writing/orders/{oid}/abstract?lang=fr", headers=auth(token))
    assert r.status_code == 422


def test_abstract_idor_404():
    client = make_client()
    token = register(client)
    oid = new_order(client, token)
    # 用另一手机号注册第二用户（同号会 409）
    r2 = client.post("/auth/register",
                     json={"phone": "13800000012", "password": PW, "check_code": "000000"})
    assert r2.status_code == 200, r2.text
    other = r2.json()["access_token"]
    r = client.post(f"/writing/orders/{oid}/abstract?lang=zh", headers=auth(other))
    assert r.status_code == 404
