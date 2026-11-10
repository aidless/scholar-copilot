"""微信回调网关：服务器签名校验 + 事件 XML 解析（公众号/服务号事件推送）。

设计要点：
- 微信服务器校验我们的 URL 时，GET 带 signature/timestamp/nonce/echostr，
  签名 = sha1( 排序后的 [token, timestamp, nonce] 拼接 )，比对通过才把 echostr 原样回。
- 事件推送走 POST，body 是 XML；用户扫描带参二维码时 Event in (subscribe, SCAN)，
  EventKey 形如 `qrscene_<scene>`（未关注时 subscribe）或直接 `<scene>`（已关注 SCAN）。
- 这里只做「纯计算」：签名校验、XML→dict 解析。不碰数据库、不碰网络，便于单测。
  真正改库（把 scene 标成 scanned/confirmed）在路由层做。
"""
import hashlib
import xml.etree.ElementTree as ET


def compute_signature(token: str, timestamp: str, nonce: str) -> str:
    """微信官方算法：token/timestamp/nonce 三个字符串字典序排序后拼接，取 sha1 十六进制。"""
    raw = "".join(sorted([token or "", str(timestamp or ""), str(nonce or "")]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def verify_signature(token: str, signature: str, timestamp: str, nonce: str) -> bool:
    """常数时间比对，避免时序侧信道（微信签名虽非敏感，但保持好习惯）。"""
    import hmac

    if not token or not signature:
        return False
    expected = compute_signature(token, timestamp, nonce)
    return hmac.compare_digest(expected, signature)


def parse_event(xml_bytes: bytes) -> dict:
    """把微信事件 XML 解析成扁平 dict（只取我们关心的字段）。

    安全：XML 一律视为不可信输入——禁用实体扩展（ElementTree 默认不展开外部实体，
    且我们不调用任何解析外部 DTD 的接口），解析失败抛 ValueError 由路由层转 400。
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"事件 XML 解析失败：{exc}") from exc

    def _text(tag: str) -> str:
        node = root.find(tag)
        return (node.text or "").strip() if node is not None else ""

    return {
        "to_user": _text("ToUserName"),
        "from_user": _text("FromUserName"),   # 即 openid
        "create_time": _text("CreateTime"),
        "msg_type": _text("MsgType"),         # event / text / ...
        "event": _text("Event"),              # subscribe / SCAN / unsubscribe / ...
        "event_key": _text("EventKey"),       # 带参二维码的场景值
        "content": _text("Content"),
        "msg_id": _text("MsgId"),
    }


def extract_scene(event_key: str) -> str:
    """从 EventKey 里取出场景值：`qrscene_abc` → `abc`；`abc` → `abc`。"""
    key = (event_key or "").strip()
    if key.startswith("qrscene_"):
        return key[len("qrscene_"):]
    return key
