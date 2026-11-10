"""认证链路：注册/登录/配额查询 + 防枚举语义。"""
from fastapi.testclient import TestClient


def make_client():
    from app.main import create_app
    return TestClient(create_app())


def test_health():
    with make_client() as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_register_login_me_full_chain():
    with make_client() as client:
        # 注册（dev 短信码 000000）
        r = client.post("/auth/register", json={
            "phone": "13800000001", "password": "Test123456", "check_code": "000000"})
        assert r.status_code == 200, r.text
        token = r.json()["access_token"]

        # 登录
        r = client.post("/auth/login", json={"phone": "13800000001", "password": "Test123456"})
        assert r.status_code == 200
        assert r.json()["access_token"]

        # me：带配额
        r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        body = r.json()
        assert body["phone"] == "13800000001"
        assert body["quota"]["remaining"] == 3


def test_register_wrong_code_rejected():
    with make_client() as client:
        r = client.post("/auth/register", json={
            "phone": "13800000002", "password": "Test123456", "check_code": "999999"})
        assert r.status_code == 400


def test_register_bad_phone_422():
    with make_client() as client:
        r = client.post("/auth/register", json={
            "phone": "abc", "password": "Test123456", "check_code": "000000"})
        assert r.status_code == 422


def test_register_duplicate_409():
    with make_client() as client:
        body = {"phone": "13800000003", "password": "Test123456", "check_code": "000000"}
        assert client.post("/auth/register", json=body).status_code == 200
        assert client.post("/auth/register", json=body).status_code == 409


def test_login_uniform_401_anti_enumeration():
    """号不存在与密码错的响应文案一致（防账号枚举）。"""
    with make_client() as client:
        client.post("/auth/register", json={
            "phone": "13800000004", "password": "Test123456", "check_code": "000000"})
        r_no_user = client.post("/auth/login", json={"phone": "13800000005", "password": "x12345678"})
        r_bad_pw = client.post("/auth/login", json={"phone": "13800000004", "password": "wrong-pass"})
        assert r_no_user.status_code == r_bad_pw.status_code == 401
        assert r_no_user.json()["detail"] == r_bad_pw.json()["detail"]
