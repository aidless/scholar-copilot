"""v1.8 #11：大纲版本历史 / 回滚 + 章节重排 / 删除。

用 fake provider 的确定性大纲（5 章）造数据，断言版本推进与 idx 连续性。
"""
from fastapi.testclient import TestClient

PHONE = "13800000011"
PW = "Test123456"


def make_client():
    from app.main import create_app
    return TestClient(create_app())


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def register(client, phone=PHONE) -> str:
    r = client.post("/auth/register",
                    json={"phone": phone, "password": PW, "check_code": "000000"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def new_order(client, token, **kw) -> str:
    body = {"title": "版本回滚测试", "education": "硕士", "word_count": 6000}
    body.update(kw)
    r = client.post("/writing/orders", json=body, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def gen_outline(client, token, oid, feedback=None):
    payload = {"feedback": feedback} if feedback else None
    r = client.post(f"/writing/orders/{oid}/outline?wait=true", json=payload,
                    headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def chapters(client, token, oid):
    r = client.get(f"/writing/orders/{oid}/chapters", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def test_outline_versions_and_get_version():
    client = make_client()
    token = register(client)
    oid = new_order(client, token)
    gen_outline(client, token, oid)
    r = client.get(f"/writing/orders/{oid}/outline/versions", headers=auth(token))
    assert r.status_code == 200
    versions = r.json()
    assert [v["version"] for v in versions] == [1]
    r = client.get(f"/writing/orders/{oid}/outline/versions/1", headers=auth(token))
    assert r.status_code == 200
    assert "第一章" in r.json()["content_md"]
    r = client.get(f"/writing/orders/{oid}/outline/versions/99", headers=auth(token))
    assert r.status_code == 404


def test_second_outline_appends_version():
    client = make_client()
    token = register(client)
    oid = new_order(client, token)
    gen_outline(client, token, oid)
    gen_outline(client, token, oid, feedback="请调整第二章结构")
    r = client.get(f"/writing/orders/{oid}/outline/versions", headers=auth(token))
    assert [v["version"] for v in r.json()] == [1, 2]


def test_rollback_appends_new_version_and_rebuilds_chapters():
    client = make_client()
    token = register(client)
    oid = new_order(client, token)
    gen_outline(client, token, oid)
    n_before = len(chapters(client, token, oid))
    assert n_before >= 5
    gen_outline(client, token, oid, feedback="换一版")
    r = client.post(f"/writing/orders/{oid}/outline/rollback",
                    json={"version": 1}, headers=auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["version"] == 3          # append-only：不改历史，新增 v3
    assert data["rolled_back_from"] == 1
    assert data["chapters_rebuilt"] is True
    # 版本历史现在 1,2,3
    vs = client.get(f"/writing/orders/{oid}/outline/versions", headers=auth(token)).json()
    assert [v["version"] for v in vs] == [1, 2, 3]
    # 章节骨架按目标版本重建，数量一致且 idx 连续
    chs = chapters(client, token, oid)
    assert len(chs) == n_before
    assert [c["idx"] for c in chs] == list(range(1, len(chs) + 1))


def test_rollback_unknown_version_404():
    client = make_client()
    token = register(client)
    oid = new_order(client, token)
    gen_outline(client, token, oid)
    r = client.post(f"/writing/orders/{oid}/outline/rollback",
                    json={"version": 42}, headers=auth(token))
    assert r.status_code == 404


def test_reorder_chapters_reverses_and_renumbers():
    client = make_client()
    token = register(client)
    oid = new_order(client, token)
    gen_outline(client, token, oid)
    chs = chapters(client, token, oid)
    ids = [c["node_id"] for c in chs]
    reversed_ids = list(reversed(ids))
    r = client.post(f"/writing/orders/{oid}/chapters/reorder",
                    json={"node_ids": reversed_ids}, headers=auth(token))
    assert r.status_code == 200, r.text
    out = r.json()
    assert [c["node_id"] for c in out] == reversed_ids
    assert [c["idx"] for c in out] == list(range(1, len(out) + 1))
    # 落库生效
    chs2 = {c["node_id"]: c["idx"] for c in chapters(client, token, oid)}
    assert chs2[reversed_ids[0]] == 1


def test_reorder_wrong_set_422():
    client = make_client()
    token = register(client)
    oid = new_order(client, token)
    gen_outline(client, token, oid)
    r = client.post(f"/writing/orders/{oid}/chapters/reorder",
                    json={"node_ids": ["ch1", "ch2"]}, headers=auth(token))
    assert r.status_code == 422


def test_delete_chapter_renumbers():
    client = make_client()
    token = register(client)
    oid = new_order(client, token)
    gen_outline(client, token, oid)
    chs = chapters(client, token, oid)
    n = len(chs)
    victim = chs[1]["node_id"]
    r = client.delete(f"/writing/orders/{oid}/chapters/{victim}", headers=auth(token))
    assert r.status_code == 204
    left = chapters(client, token, oid)
    assert len(left) == n - 1
    assert [c["idx"] for c in left] == list(range(1, n))
    assert victim not in [c["node_id"] for c in left]


def test_versions_idor_404():
    client = make_client()
    token = register(client)
    oid = new_order(client, token)
    gen_outline(client, token, oid)
    other = register(client, "13800000012")
    r = client.get(f"/writing/orders/{oid}/outline/versions", headers=auth(other))
    assert r.status_code == 404
    r = client.post(f"/writing/orders/{oid}/outline/rollback",
                    json={"version": 1}, headers=auth(other))
    assert r.status_code == 404
