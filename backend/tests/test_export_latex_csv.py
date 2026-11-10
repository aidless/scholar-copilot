"""v1.3：LaTeX 导出（ctexart 可编译骨架）+ 管理端 CSV 对账导出。"""
import os

from fastapi.testclient import TestClient

PW = "Test123456"
ADMIN_PW = os.environ.get("SC_ADMIN_INITIAL_PASSWORD", "")


def make_client():
    from app.main import create_app
    return TestClient(create_app())


def auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_export_tex_and_latex_escaping():
    with make_client() as client:
        tok = client.post("/auth/register", json={
            "phone": "13900001001", "password": PW, "check_code": "000000"}).json()["access_token"]
        o = client.post("/writing/orders", headers=auth(tok), json={
            "title": "LaTeX_导出 & 转义%测试", "education": "博士", "word_count": 6000}).json()
        client.post(f"/writing/orders/{o['id']}/outline?wait=true", headers=auth(tok), json={"feedback": None})
        p = client.post(f"/payments/orders/{o['id']}", headers=auth(tok), json={"pay_method": "wechat"}).json()
        client.post(f"/payments/{p['serial_no']}/confirm", headers=auth(tok))
        for ch in client.get(f"/writing/orders/{o['id']}/chapters", headers=auth(tok)).json():
            assert client.post(f"/writing/orders/{o['id']}/chapters/{ch['node_id']}?wait=true",
                               headers=auth(tok)).status_code == 200

        r = client.post(f"/writing/orders/{o['id']}/export?format=tex", headers=auth(tok))
        assert r.status_code == 200, r.text[:300]
        tex = r.content.decode("utf-8")
        assert tex.startswith("\\documentclass")
        assert "ctexart" in tex and "\\begin{document}" in tex and "\\end{document}" in tex
        assert "AI 参与度披露" in tex and "免责声明" in tex
        assert "\\_" in tex and "\\&" in tex and "\\%" in tex  # 特殊字符已转义


def test_admin_csv_exports():
    with make_client() as client:
        adm = client.post("/admin/login", json={"username": "admin", "password": "t3st-Adm1n-Pw!"}).json()["access_token"]
        tok = client.post("/auth/register", json={
            "phone": "13900001002", "password": PW, "check_code": "000000"}).json()["access_token"]
        client.post("/writing/orders", headers=auth(tok), json={
            "title": "CSV 对账", "education": "本科", "word_count": 6000})

        for kind, header in [("orders", "id,tenant_id,owner_id,title"),
                             ("payments", "id,serial_no,order_id"),
                             ("commissions", "id,distributor_id,order_id"),
                             ("audit", "id,admin_id,action")]:
            r = client.get(f"/admin/exports/{kind}.csv", headers=auth(adm))
            assert r.status_code == 200, r.text[:200]
            assert "text/csv" in r.headers["content-type"]
            text = r.content.decode("utf-8-sig")
            assert text.splitlines()[0].startswith(header)

        assert client.get("/admin/exports/nope.csv", headers=auth(adm)).status_code == 404
        # 导出动作留审计
        logs = client.get("/admin/audit-log", headers=auth(adm)).json()
        assert any(x["action"].startswith("export.csv.") for x in logs)
