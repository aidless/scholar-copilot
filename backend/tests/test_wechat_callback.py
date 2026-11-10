"""微信真实回调网关：签名校验 + 事件解析 + 扫码会话推进。

不需要真实公众号：签名算法是公开的 sha1 排序拼接，事件 XML 是我们自己造的标准报文。
"""
import hashlib

import pytest

from app import wechat as wx
from app.config import settings


def _sign(token, timestamp, nonce):
    return wx.compute_signature(token, timestamp, nonce)


def test_signature_matches_wechat_official_algorithm():
    """签名 = sha1(字典序排序 [token,timestamp,nonce] 拼接)，与官方文档一致。"""
    token, ts, nonce = "abc123", "1700000000", "xyz"
    raw = "".join(sorted([token, ts, nonce]))
    assert wx.compute_signature(token, ts, nonce) == hashlib.sha1(raw.encode()).hexdigest()


def test_verify_signature_true_and_false():
    token, ts, nonce = "tok", "123", "456"
    good = _sign(token, ts, nonce)
    assert wx.verify_signature(token, good, ts, nonce) is True
    assert wx.verify_signature(token, "deadbeef", ts, nonce) is False
    assert wx.verify_signature("", good, ts, nonce) is False  # 未配 token 一律 false


def test_extract_scene_strips_qrscene_prefix():
    assert wx.extract_scene("qrscene_abc123") == "abc123"
    assert wx.extract_scene("abc123") == "abc123"
    assert wx.extract_scene("") == ""


def test_parse_event_subscribe_scan():
    xml = b"""<xml>
    <ToUserName><![CDATA[gh_123]]></ToUserName>
    <FromUserName><![CDATA[oUSER_openid_1]]></FromUserName>
    <CreateTime>1700000000</CreateTime>
    <MsgType><![CDATA[event]]></MsgType>
    <Event><![CDATA[SCAN]]></Event>
    <EventKey><![CDATA[qrscene_sceneA]]></EventKey>
    </xml>"""
    ev = wx.parse_event(xml)
    assert ev["event"] == "SCAN"
    assert ev["from_user"] == "oUSER_openid_1"
    assert ev["msg_type"] == "event"
    assert wx.extract_scene(ev["event_key"]) == "sceneA"


def test_parse_event_bad_xml_raises():
    with pytest.raises(ValueError):
        wx.parse_event(b"<xml>not closed")


# ── 路由层：URL 校验握手 + 事件推送推进会话 ───────────────────────────────

import pytest as _pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import create_app
    with TestClient(create_app()) as c:
        yield c


def _patch_token(monkeypatch, token="wxtok"):
    monkeypatch.setattr(settings, "wechat_token", token)


def _event_xml(scene, openid, event="SCAN"):
    return f"""<xml><ToUserName><![CDATA[gh_1]]></ToUserName>
    <FromUserName><![CDATA[{openid}]]></FromUserName>
    <CreateTime>1700000000</CreateTime>
    <MsgType><![CDATA[event]]></MsgType>
    <Event><![CDATA[{event}]]></Event>
    <EventKey><![CDATA[qrscene_{scene}]]></EventKey></xml>""".encode()


def _push_event(client, xml, sig):
    return client.post(f"/auth/wechat/callback?signature={sig}&timestamp=123&nonce=456",
                       content=xml, headers={"Content-Type": "text/xml"})


def test_callback_get_echo_ok(client, monkeypatch):
    _patch_token(monkeypatch)
    sig = _sign("wxtok", "123", "456")
    r = client.get("/auth/wechat/callback",
                   params={"signature": sig, "timestamp": "123", "nonce": "456",
                           "echostr": "hello-wechat"})
    assert r.status_code == 200
    assert r.text == "hello-wechat"


def test_callback_get_bad_signature_403(client, monkeypatch):
    _patch_token(monkeypatch)
    r = client.get("/auth/wechat/callback",
                   params={"signature": "wrong", "timestamp": "123", "nonce": "456",
                           "echostr": "x"})
    assert r.status_code == 403


def test_callback_not_configured_503(client, monkeypatch):
    monkeypatch.setattr(settings, "wechat_token", "")
    r = client.get("/auth/wechat/callback",
                   params={"signature": "x", "timestamp": "1", "nonce": "2", "echostr": "y"})
    assert r.status_code == 503


def _make_scene(client):
    return client.post("/auth/wechat/qrcode").json()["scene"]


def test_event_scan_bad_signature_403(client, monkeypatch):
    _patch_token(monkeypatch)
    scene = _make_scene(client)
    r = _push_event(client, _event_xml(scene, "oX"), "wrongsig")
    assert r.status_code == 403


def test_event_scan_marks_scene_scanned(client, monkeypatch):
    """用户扫码 → 回调事件 → 会话从 pending 变 scanned，并记下 openid。"""
    _patch_token(monkeypatch)
    scene = _make_scene(client)
    sig = _sign("wxtok", "123", "456")
    r = _push_event(client, _event_xml(scene, "oOpenidX"), sig)
    assert r.status_code == 200 and r.text == "success"
    poll = client.get(f"/auth/wechat/poll?scene={scene}").json()
    assert poll["status"] == "scanned"


def test_complete_binds_new_user_and_confirms(client, monkeypatch):
    """扫码后 /wechat/complete：用手机号建号并绑定 openid，返回 token。"""
    _patch_token(monkeypatch)
    scene = _make_scene(client)
    sig = _sign("wxtok", "123", "456")
    _push_event(client, _event_xml(scene, "oNEW_1"), sig)
    r = client.post("/auth/wechat/complete", json={"scene": scene, "phone": "13900000002"})
    assert r.status_code == 200
    assert "access_token" in r.json()
    assert client.get(f"/auth/wechat/poll?scene={scene}").json()["status"] == "confirmed"


def test_bound_openid_second_scan_auto_confirms(client, monkeypatch):
    """openid 绑定后，再次扫码应直接完成登录（不需要再填手机号）。"""
    _patch_token(monkeypatch)
    sig = _sign("wxtok", "123", "456")
    openid = "oBOUND_1"
    # 第一次：扫码 + complete 绑定 openid
    s1 = _make_scene(client)
    _push_event(client, _event_xml(s1, openid), sig)
    client.post("/auth/wechat/complete", json={"scene": s1, "phone": "13900000001"})
    # 第二次：新 scene，同一 openid 扫码 → 直接 confirmed
    s2 = _make_scene(client)
    _push_event(client, _event_xml(s2, openid, event="subscribe"), sig)
    poll = client.get(f"/auth/wechat/poll?scene={s2}").json()
    assert poll["status"] == "confirmed"
    assert "access_token" in poll


def test_complete_requires_phone_for_new_scene(client, monkeypatch):
    _patch_token(monkeypatch)
    scene = _make_scene(client)
    r = client.post("/auth/wechat/complete", json={"scene": scene, "phone": "bad"})
    assert r.status_code == 422


def test_complete_unknown_scene_404(client, monkeypatch):
    _patch_token(monkeypatch)
    r = client.post("/auth/wechat/complete", json={"scene": "nope", "phone": "13900000002"})
    assert r.status_code == 404
