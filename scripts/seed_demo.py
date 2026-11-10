"""给「刚 clone 下来想看点什么」的人灌一份演示数据。

用法（对着一个已经在跑的后端）：
    python scripts/seed_demo.py                          # 默认 http://127.0.0.1:8000
    python scripts/seed_demo.py --base http://host:8000
    python scripts/seed_demo.py --admin-password 'xxx'   # 顺便创建/登录管理员

会创建：
  - 演示用户 13800000000 / Demo-pass-2026（已存在则直接登录）
  - 一笔「本科 6000 字」订单，跑完 大纲 → 逐章 → 支付 → 导出
  - 打印可直接在 /workbench 打开的订单摘要与账号

注意：这脚本会**真的调用生成接口**。fake provider 下几秒完成；接真实模型时按
章数会花几分钟、并按字数计费，请自行确认。

为什么需要它：`docker compose up` 起来后是空库，第一次登录的人面对空白页
不知道该点哪。有一条命令能灌出一份「已经写完的论文」，演示成本才低。
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:8000"
DEMO_PHONE = "13800000000"
DEMO_PASSWORD = "Demo-pass-2026"
DEMO_CODE = "000000"   # SC_SMS_DEV_MODE=true 下的万能验证码


def _call(base, method, path, body=None, token=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            payload = r.read()
            return payload if raw else json.loads(payload)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:400]
        raise SystemExit(f"{method} {path} → HTTP {e.code}: {detail}")


def _login_or_register(base):
    """先尝试登录；账号不存在才注册（避免每次都吃一次注册限流）。"""
    try:
        out = _call(base, "POST", "/auth/login",
                    {"phone": DEMO_PHONE, "password": DEMO_PASSWORD})
        print(f"  复用已有演示账号 {DEMO_PHONE}")
        return out["access_token"]
    except SystemExit:
        pass
    out = _call(base, "POST", "/auth/register",
                {"phone": DEMO_PHONE, "password": DEMO_PASSWORD, "check_code": DEMO_CODE})
    print(f"  新建演示账号 {DEMO_PHONE}")
    return out["access_token"]


def _wait_job(base, job_id, token, timeout=600, label=""):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = _call(base, "GET", f"/jobs/{job_id}", None, token)
        if s["status"] in ("done", "failed"):
            if s["status"] == "failed":
                raise SystemExit(f"{label} 生成失败：{s.get('error')}")
            return s
        time.sleep(0.8)
    raise SystemExit(f"{label} 超时（{timeout}s 未完成）")


def main(argv=None):
    ap = argparse.ArgumentParser(description="灌一份演示数据")
    ap.add_argument("--base", default=DEFAULT_BASE, help="后端地址")
    ap.add_argument("--title", default="人工智能在中小学教育中的应用研究")
    ap.add_argument("--education", default="本科", choices=["本科", "硕士", "博士"])
    ap.add_argument("--words", type=int, default=6000)
    args = ap.parse_args(argv)

    base = args.base.rstrip("/")
    print(f"目标后端：{base}")
    print(_call(base, "GET", "/health"))

    print("== 1/5 账号 ==")
    tok = _login_or_register(base)

    print("== 2/5 下单 ==")
    order = _call(base, "POST", "/writing/orders", {
        "title": args.title, "education": args.education, "word_count": args.words}, tok)
    oid = order["id"]
    print(f"  订单 {oid}：{args.words} 字 × {args.education} → {order['price_cents']} 分")

    print("== 3/5 大纲 ==")
    t0 = time.time()
    job = _call(base, "POST", f"/writing/orders/{oid}/outline", {"feedback": None}, tok)["job_id"]
    s = _wait_job(base, job, tok, label="大纲")
    print(f"  {s['result']['chapters']} 章（{time.time()-t0:.1f}s，模型 {s['model']}）")

    print("== 4/5 支付 + 逐章生成 ==")
    pay = _call(base, "POST", f"/payments/orders/{oid}", {"pay_method": "wechat"}, tok)
    _call(base, "POST", f"/payments/{pay['serial_no']}/confirm", {}, tok)
    print(f"  已支付 {pay['amount_cents']} 分（{pay.get('status')}）")
    chapters = _call(base, "GET", f"/writing/orders/{oid}/chapters", None, tok)
    t0 = time.time()
    for i, c in enumerate(chapters, 1):
        r = _call(base, "POST", f"/writing/orders/{oid}/chapters/{c['node_id']}", {}, tok)
        _wait_job(base, r["job_id"], tok, label=f"第 {i} 章")
        print(f"  [{i}/{len(chapters)}] {c['title']}")
    print(f"  全部完成（{time.time()-t0:.1f}s）")

    print("== 5/5 导出 ==")
    docx = _call(base, "POST", f"/writing/orders/{oid}/export", {}, tok, raw=True)
    out = f"/tmp/scholar-copilot-demo/seed-{oid[:8]}.docx"
    import os
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(docx)
    print(f"  {len(docx)} 字节 → {out}")

    print("\n=== 演示账号 ===")
    print(f"  手机号：{DEMO_PHONE}")
    print(f"  密码：  {DEMO_PASSWORD}")
    print(f"  订单：  {oid}（前端 /workbench 里可继续改稿/重新导出）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
