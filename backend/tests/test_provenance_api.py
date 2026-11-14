"""#19 指纹链接入端到端：生成 → 改稿 → 链上有据可查（API 层，RED→GREEN）。"""
from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app())


def _register_and_order():
    import time
    phone = f"139{int(time.time()) % 100000000:08d}"
    r = client.post("/auth/register", json={
        "phone": phone, "password": "Test-kshi-9382", "check_code": "000000"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    o = client.post("/writing/orders", headers=h, json={
        "title": "指纹链测试论文", "education": "本科", "word_count": 6000})
    assert o.status_code == 200, o.text
    return h, o.json()["id"]


def test_provenance_chain_endpoint_exists_and_lists():
    h, order_id = _register_and_order()
    resp = client.get(f"/writing/orders/{order_id}/provenance", headers=h)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "chain" in data
    assert isinstance(data["chain"], list)


def test_provenance_chain_records_generation():
    h, order_id = _register_and_order()
    # 生成大纲（fake provider）→ 落章节骨架
    r = client.post(f"/writing/orders/{order_id}/outline", headers=h, params={"wait": True})
    assert r.status_code == 200, r.text
    resp = client.get(f"/writing/orders/{order_id}/provenance", headers=h)
    chain = resp.json()["chain"]
    assert chain, "生成后链上应有记录"
    kinds = {c["kind"] for c in chain}
    assert "outline" in kinds
    for c in chain:
        assert len(c["content_sha256"]) == 64
        assert c["ai_level"] in {"A", "B", "C"}


def test_edit_chapter_appends_to_chain():
    h, order_id = _register_and_order()
    client.post(f"/writing/orders/{order_id}/outline", headers=h, params={"wait": True})
    # 先生成正文（A 级），再人工改写 → 链上应出现 generate + edit 两条
    pay = client.post(f"/payments/orders/{order_id}", headers=h,
                      json={"pay_method": "alipay"})
    assert pay.status_code == 200, pay.text
    conf = client.post(f"/payments/{pay.json()['serial_no']}/confirm", headers=h)
    assert conf.status_code == 200, conf.text
    chapters = client.get(f"/writing/orders/{order_id}/chapters", headers=h).json()
    node = chapters[0]["node_id"]
    g = client.post(f"/writing/orders/{order_id}/chapters/{node}", headers=h,
                    params={"wait": True})
    assert g.status_code == 200, g.text
    before = client.get(f"/writing/orders/{order_id}/provenance", headers=h).json()
    e = client.put(f"/writing/orders/{order_id}/chapters/{node}", headers=h, json={
        "content_md": "这是人工改写后的章节内容，含有具体数据与分析结论。"})
    assert e.status_code == 200, e.text
    after = client.get(f"/writing/orders/{order_id}/provenance", headers=h).json()
    assert len(after["chain"]) > len(before["chain"]), "改稿必须往链上追加记录"
    last = after["chain"][-1]
    assert last["kind"] == "edit"
    assert last["node_id"] == node
    # 「AI 初稿被人工改过」的客观证据：相似度 < 1.0
    assert last["similarity"] is not None
    assert last["similarity"] < 1.0
    # 人工改稿后层级自动从 A 升到 B
    assert after["latest_levels"][node] == "B"
    assert node in after["human_edited_nodes"]


def test_provenance_chain_is_idor_protected():
    h, order_id = _register_and_order()
    client.post(f"/writing/orders/{order_id}/outline", headers=h, params={"wait": True})
    resp = client.get(f"/writing/orders/{order_id}/provenance", headers=h)
    assert resp.status_code == 200
    # 另一个用户访问 → 404（统一不区分不存在/非属主）
    import time
    phone2 = f"138{int(time.time() + 7) % 100000000:08d}"
    r2 = client.post("/auth/register", json={
        "phone": phone2, "password": "Test-kshi-9383", "check_code": "000000"})
    h2 = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    resp2 = client.get(f"/writing/orders/{order_id}/provenance", headers=h2)
    assert resp2.status_code == 404
