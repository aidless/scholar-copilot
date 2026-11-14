"""v1.2：短信验证码（库内哈希 + 无状态 oracle）、微信扫码登录（dev mock）、任务队列抽象。"""
from fastapi.testclient import TestClient

PW = "Test123456"


def make_client():
    from app.main import create_app
    return TestClient(create_app())


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_sms_send_and_register_with_real_code():
    with make_client() as client:
        r = client.post("/auth/sms/send", json={"phone": "13900000001", "scene": "register"})
        assert r.status_code == 200, r.text
        code = r.json()["dev_code"]
        assert len(code) == 6 and code.isdigit()

        # 错误验证码
        assert client.post("/auth/register", json={
            "phone": "13900000001", "password": PW, "check_code": "111111"}).status_code == 400
        # 正确验证码
        r = client.post("/auth/register", json={
            "phone": "13900000001", "password": PW, "check_code": code})
        assert r.status_code == 200, r.text
        tok = r.json()["access_token"]

        # 一次性：同一码再用 → 400
        assert client.post("/auth/sms/send", json={"phone": "13900000002", "scene": "register"}).status_code == 200
        assert client.post("/auth/register", json={
            "phone": "13900000002", "password": PW, "check_code": code}).status_code == 400
        assert client.get("/auth/me", headers=auth(tok)).status_code == 200


def test_sms_send_does_not_leak_registration_state():
    """已注册号与未注册号响应字段完全一致（不给注册状态 oracle）。"""
    with make_client() as client:
        client.post("/auth/register", json={"phone": "13900000003", "password": PW, "check_code": "000000"})
        a = client.post("/auth/sms/send", json={"phone": "13900000003", "scene": "login"})
        b = client.post("/auth/sms/send", json={"phone": "13900000004", "scene": "login"})
        assert a.status_code == b.status_code == 200
        assert set(a.json()) == set(b.json())
        assert a.json()["expires_in"] == b.json()["expires_in"]


def test_wechat_mock_login_flow():
    with make_client() as client:
        r = client.post("/auth/wechat/qrcode")
        assert r.status_code == 200 and r.json()["mode"] == "dev"
        scene = r.json()["scene"]
        assert client.get(f"/auth/wechat/poll?scene={scene}").json()["status"] == "pending"

        assert client.post("/auth/wechat/mock-approve",
                           json={"scene": scene, "phone": "13900000005"}).status_code == 200
        out = client.get(f"/auth/wechat/poll?scene={scene}").json()
        assert out["status"] == "confirmed" and out["access_token"]
        assert client.get("/auth/me", headers=auth(out["access_token"])).status_code == 200


def test_wechat_mock_approve_forbidden_outside_dev(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "sms_dev_mode", False)
    with make_client() as client:
        assert client.post("/auth/wechat/mock-approve",
                           json={"scene": "x", "phone": "13900000006"}).status_code == 403


def test_queue_arq_path_enqueues_without_running(monkeypatch):
    """SC_TASK_QUEUE=arq 时端点只投递任务，不在请求内执行生成。"""
    from app.config import settings
    from app.tasks import queue as q

    calls = []

    class FakePool:
        async def enqueue_job(self, name, job_id):
            calls.append((name, job_id))

    async def fake_pool():
        return FakePool()

    monkeypatch.setattr(settings, "task_queue", "arq")
    monkeypatch.setattr(q, "_get_pool", fake_pool)

    with make_client() as client:
        tok = client.post("/auth/register", json={
            "phone": "13900000007", "password": PW, "check_code": "000000"}).json()["access_token"]
        o = client.post("/writing/orders", headers=auth(tok), json={
            "title": "队列测试", "education": "本科", "word_count": 6000}).json()
        r = client.post(f"/writing/orders/{o['id']}/outline", headers=auth(tok), json={"feedback": None})
        assert r.status_code in (200, 202), r.text
        job_id = r.json()["job_id"]
        assert calls == [("run_job_task", job_id)]
        # 未执行 → job 仍 queued
        assert client.get(f"/jobs/{job_id}", headers=auth(tok)).json()["status"] == "queued"
