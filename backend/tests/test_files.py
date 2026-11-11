"""v1.9 #2/#14：文件上传 + 对象存储 + 元数据表（白名单/上限/IDOR/回读）。"""
import pytest
from fastapi.testclient import TestClient

PHONE = "13800000011"
PHONE2 = "13800000012"
PW = "Test123456"


def make_client():
    from app.main import create_app
    return TestClient(create_app())


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def register(client, phone=PHONE):
    r = client.post("/auth/register",
                    json={"phone": phone, "password": PW, "check_code": "000000"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(autouse=True)
def _tmp_storage(tmp_path, monkeypatch):
    from app import storage
    from app.config import settings
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "uploads"))
    storage.reset_storage()
    yield
    storage.reset_storage()


def test_upload_and_download_roundtrip():
    client = make_client()
    token = register(client)
    payload = b"hello scholar copilot upload"
    r = client.post("/files", files={"upload": ("note.txt", payload, "text/plain")},
                    data={"kind": "outline_report"}, headers=auth(token))
    assert r.status_code == 201, r.text
    meta = r.json()
    assert meta["filename"] == "note.txt"
    assert meta["size"] == len(payload)
    assert meta["kind"] == "outline_report"
    assert len(meta["sha256"]) == 64
    fid = meta["id"]
    # 下载回读一致
    r = client.get(f"/files/{fid}/download", headers=auth(token))
    assert r.status_code == 200
    assert r.content == payload
    # 元数据
    r = client.get(f"/files/{fid}", headers=auth(token))
    assert r.status_code == 200 and r.json()["id"] == fid


def test_upload_rejects_bad_extension():
    client = make_client()
    token = register(client)
    r = client.post("/files", files={"upload": ("evil.exe", b"MZ", "application/octet-stream")},
                    headers=auth(token))
    assert r.status_code == 422


def test_upload_rejects_empty():
    client = make_client()
    token = register(client)
    r = client.post("/files", files={"upload": ("empty.txt", b"", "text/plain")},
                    headers=auth(token))
    assert r.status_code == 422


def test_upload_rejects_oversize(monkeypatch):
    client = make_client()
    token = register(client)
    from app.config import settings
    monkeypatch.setattr(settings, "max_upload_mb", 0)  # 任何非空都超限
    r = client.post("/files", files={"upload": ("big.txt", b"x" * 10, "text/plain")},
                    headers=auth(token))
    assert r.status_code == 413


def test_list_files_and_kind_filter():
    client = make_client()
    token = register(client)
    client.post("/files", files={"upload": ("a.txt", b"aaa", "text/plain")},
                data={"kind": "attachment"}, headers=auth(token))
    client.post("/files", files={"upload": ("b.md", b"bbb", "text/markdown")},
                data={"kind": "template"}, headers=auth(token))
    r = client.get("/files", headers=auth(token))
    assert r.status_code == 200 and len(r.json()) == 2
    r = client.get("/files?kind=template", headers=auth(token))
    assert len(r.json()) == 1 and r.json()[0]["filename"] == "b.md"


def test_download_idor_404():
    client = make_client()
    token = register(client, PHONE)
    r = client.post("/files", files={"upload": ("a.txt", b"aaa", "text/plain")},
                    headers=auth(token))
    fid = r.json()["id"]
    other = register(client, PHONE2)
    r = client.get(f"/files/{fid}/download", headers=auth(other))
    assert r.status_code == 404
    r = client.get(f"/files/{fid}/signed-url", headers=auth(other))
    assert r.status_code == 404


def test_delete_removes_row_and_blob():
    client = make_client()
    token = register(client)
    r = client.post("/files", files={"upload": ("a.txt", b"aaa", "text/plain")},
                    headers=auth(token))
    fid = r.json()["id"]
    r = client.delete(f"/files/{fid}", headers=auth(token))
    assert r.status_code == 204
    r = client.get(f"/files/{fid}", headers=auth(token))
    assert r.status_code == 404


def test_signed_url_local_backend():
    client = make_client()
    token = register(client)
    r = client.post("/files", files={"upload": ("a.txt", b"aaa", "text/plain")},
                    headers=auth(token))
    fid = r.json()["id"]
    r = client.get(f"/files/{fid}/signed-url", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["url"].startswith("/files/download?key=")


def test_storage_key_traversal_guard():
    from app.storage import LocalStorage, StorageError
    import tempfile
    s = LocalStorage(tempfile.mkdtemp())
    with pytest.raises(StorageError):
        s._path("../escape.txt")
