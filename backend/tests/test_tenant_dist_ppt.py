"""v1.1：白标租户 branding（不泄密）/ 分销佣金与提现 / PPT 与 Mermaid 生成 / PDF 导出。"""
import pytest
from fastapi.testclient import TestClient

PHONE_U = "13800000001"
PHONE_U2 = "13800000011"
PW = "Test123456"


def make_client():
    from app.main import create_app
    return TestClient(create_app())


def admin_token(client) -> str:
    r = client.post("/admin/login", json={"username": "admin", "password": "t3st-Adm1n-Pw!"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def user_token(client, phone=PHONE_U) -> str:
    r = client.post("/auth/register", json={"phone": phone, "password": PW, "check_code": "000000"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------------------------------------------------------------- 租户 branding
def test_tenant_branding_never_leaks_secrets():
    with make_client() as client:
        adm = admin_token(client)
        r = client.post("/admin/tenants", headers=auth(adm),
                        json={"name": "云笔学术", "domain": "lab.example.com", "plan": "pro"})
        assert r.status_code == 201, r.text
        tid = r.json()["id"]

        r = client.put(f"/admin/tenants/{tid}/config", headers=auth(adm),
                       json={"brand_color": "#1d4ed8", "logo_url": "https://cdn.example.com/logo.png",
                             "support_contact": "kf@example.com"})
        assert r.status_code == 200, r.text

        r = client.get("/tenant/branding", headers={"Host": "lab.example.com"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tenant_id"] == tid and body["name"] == "云笔学术"
        assert body["brand_color"] == "#1d4ed8"
        # 字段白名单：绝不能出现任何密钥/渠道凭据
        assert set(body) <= {"tenant_id", "name", "domain", "plan", "brand_color",
                             "logo_url", "support_contact"}
        text = r.text.lower()
        for banned in ("secret", "appsecret", "token", "aeskey", "key"):
            assert banned not in text

        # 未绑定域名 → 回退 primary（不报错、不泄露）
        r = client.get("/tenant/branding", headers={"Host": "unknown.example.com"})
        assert r.status_code == 200 and r.json()["tenant_id"] == "primary"


# ---------------------------------------------------------------- 分销
def test_distributor_commission_and_withdraw():
    with make_client() as client:
        adm = admin_token(client)
        r = client.post("/admin/distributors", headers=auth(adm),
                        json={"name": "校园代理A", "phone": PHONE_U2, "code": "CAMPUS01", "rate_bps": 500})
        assert r.status_code == 201, r.text
        dist_id = r.json()["id"]
        assert client.post("/admin/distributors", headers=auth(adm),
                           json={"name": "重复", "phone": PHONE_U2, "code": "CAMPUS01"}
                           ).status_code == 409

        ut = user_token(client)
        o = client.post("/writing/orders", headers=auth(ut), json={
            "title": "分销渠道论文", "education": "本科", "word_count": 12000,
            "distributor_code": "CAMPUS01"}).json()
        assert o["price_cents"] == 36000

        # 未支付 → 无佣金
        assert client.get("/admin/commissions", headers=auth(adm)).json() == []

        p = client.post(f"/payments/orders/{o['id']}", headers=auth(ut),
                        json={"pay_method": "wechat"}).json()
        client.post(f"/payments/{p['serial_no']}/confirm", headers=auth(ut))

        rows = client.get("/admin/commissions", headers=auth(adm)).json()
        assert len(rows) == 1
        c = rows[0]
        assert c["amount_cents"] == 1800 and c["rate_bps"] == 500 and c["status"] == "pending"
        assert c["distributor_id"] == dist_id

        # 未结算前不可提现
        dl = client.post("/distributor/login", json={"code": "CAMPUS01", "phone": PHONE_U2})
        assert dl.status_code == 200
        dt = dl.json()["access_token"]
        assert client.get("/distributor/me", headers=auth(dt)).json()["withdrawable_cents"] == 0
        assert client.post("/distributor/transfers", headers=auth(dt),
                           json={"amount_cents": 100}).status_code == 400

        # 结算 → 可提现 1800
        assert client.post(f"/admin/commissions/{c['id']}/settle", headers=auth(adm)).json()["status"] == "settled"
        me = client.get("/distributor/me", headers=auth(dt)).json()
        assert me["commission_settled_cents"] == 1800 and me["withdrawable_cents"] == 1800

        tr = client.post("/distributor/transfers", headers=auth(dt), json={"amount_cents": 1800}).json()
        assert tr["status"] == "requested"
        # 已申请额占满 → 再申请 400
        assert client.post("/distributor/transfers", headers=auth(dt),
                           json={"amount_cents": 1}).status_code == 400

        # 管理端放款（留审计）
        assert client.post(f"/admin/distributor-transfers/{tr['id']}/pay", headers=auth(adm)
                           ).json()["status"] == "paid"
        logs = client.get("/admin/audit-log", headers=auth(adm)).json()
        actions = [x["action"] for x in logs]
        assert "distributor.create" in actions and "commission.settle" in actions
        assert "distributor.transfer.pay" in actions


def test_distributor_login_uniform_401():
    with make_client() as client:
        adm = admin_token(client)
        client.post("/admin/distributors", headers=auth(adm),
                    json={"name": "代理B", "phone": PHONE_U2, "code": "CAMPUS02"})
        a = client.post("/distributor/login", json={"code": "NOPE", "phone": PHONE_U2})
        b = client.post("/distributor/login", json={"code": "CAMPUS02", "phone": "13000000000"})
        assert a.status_code == b.status_code == 401
        assert a.json()["detail"] == b.json()["detail"]  # 防枚举：文案一致


# ---------------------------------------------------------------- PPT / 图表
def test_make_ppt_downloads_pptx():
    with make_client() as client:
        r = client.post("/tools/ppt", json={"topic": "深度学习在学术写作中的应用", "pages": 8})
        assert r.status_code == 200, r.text
        assert r.content[:2] == b"PK" and len(r.content) > 20000
        assert "presentationml" in r.headers["content-type"]
        assert ".pptx" in r.headers["content-disposition"]


def test_make_diagram_returns_mermaid():
    with make_client() as client:
        r = client.post("/tools/diagram", json={"description": "用户下单到导出的流程", "kind": "flowchart"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mermaid"].startswith("flowchart")
        assert "用户下单" in body["mermaid"]


# ---------------------------------------------------------------- PDF 导出（真实 LibreOffice）
def test_export_pdf_real_conversion():
    with make_client() as client:
        ut = user_token(client)
        o = client.post("/writing/orders", headers=auth(ut), json={
            "title": "PDF 导出验证", "education": "硕士", "word_count": 6000}).json()
        client.post(f"/writing/orders/{o['id']}/outline?wait=true", headers=auth(ut), json={"feedback": None})
        p = client.post(f"/payments/orders/{o['id']}", headers=auth(ut), json={"pay_method": "alipay"}).json()
        client.post(f"/payments/{p['serial_no']}/confirm", headers=auth(ut))
        chs = client.get(f"/writing/orders/{o['id']}/chapters", headers=auth(ut)).json()
        for ch in chs:
            assert client.post(f"/writing/orders/{o['id']}/chapters/{ch['node_id']}?wait=true",
                               headers=auth(ut)).status_code == 200

        r = client.post(f"/writing/orders/{o['id']}/export?format=pdf", headers=auth(ut))
        assert r.status_code == 200, r.text[:400]
        assert r.content[:4] == b"%PDF"
        assert "application/pdf" in r.headers["content-type"]
