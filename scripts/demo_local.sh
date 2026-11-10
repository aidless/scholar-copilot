#!/usr/bin/env bash
# 一键演示：不需要 Docker、不需要 LLM 密钥、不需要 Postgres。
#
#   bash scripts/demo_local.sh
#
# 会做：
#   1. 用 SQLite + 进程内队列 + fake provider 起后端（随机端口）
#   2. 注册演示账号 → 下单 → 出大纲 → 逐章生成 → 支付 → 导出 DOCX
#   3. 把生成的 docx 放到 /tmp/scholar-copilot-demo/，并打印每步耗时
#   4. 退出时杀掉后端进程
#
# 为什么单独有这个脚本：`docker compose up` 是完整形态，但要构建镜像、要密钥、
# 要三个端口。想看「它到底能干什么」的人应该有一条 30 秒的路。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
OUT_DIR="${DEMO_OUT_DIR:-/tmp/scholar-copilot-demo}"
PORT="${DEMO_PORT:-8931}"
PY="${PYTHON:-python3}"

mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR/demo.db"

echo "== 1/2 启动后端（SQLite + fake provider，端口 $PORT）=="
cd "$BACKEND"
SC_DATABASE_URL="sqlite+aiosqlite:///$OUT_DIR/demo.db" \
SC_JWT_SECRET="demo-only-not-for-production" \
SC_LLM_PROVIDER="fake" \
SC_SMS_DEV_MODE="true" \
SC_PAYMENT_MODE="mock" \
SC_TASK_QUEUE="inline" \
SC_RATE_LIMIT_BACKEND="memory" \
SC_DB_AUTO_CREATE="true" \
  "$PY" -m uvicorn app.main:app --port "$PORT" --log-level warning > "$OUT_DIR/backend.log" 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT

for i in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:$PORT/health" > /dev/null 2>&1; then break; fi
  sleep 0.5
done
if ! curl -sf "http://127.0.0.1:$PORT/health" > /dev/null; then
  echo "后端没起来，日志："; tail -30 "$OUT_DIR/backend.log"; exit 1
fi
echo "   后端就绪：$(curl -s "http://127.0.0.1:$PORT/health")"

echo "== 2/2 跑完整业务流 =="
BASE_URL="http://127.0.0.1:$PORT" OUT_DIR="$OUT_DIR" "$PY" - <<'PY'
import json, os, time, urllib.request, zipfile

B = os.environ["BASE_URL"]
OUT = os.environ["OUT_DIR"]


def call(method, path, body=None, token=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(B + path, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req) as r:
        return r.read() if raw else json.loads(r.read())


def step(msg):
    print(f"   {msg}")


t0 = time.time()
phone = "139" + f"{int(time.time()) % 100000000:08d}"
tok = call("POST", "/auth/register", {
    "phone": phone, "password": "demo-password-1", "check_code": "000000"})["access_token"]
step(f"注册 {phone} → 拿到 token（{time.time()-t0:.1f}s）")

order = call("POST", "/writing/orders", {
    "title": "人工智能在教育领域的应用研究", "education": "本科",
    "word_count": 6000}, tok)
step(f"下单 id={order['id']} 服务端计价={order['price_cents']} 分"
     f"（{order['word_count']} 字 × {order['education']}）")

t = time.time()
job = call("POST", f"/writing/orders/{order['id']}/outline", {"feedback": None}, tok)["job_id"]
for _ in range(60):
    s = call("GET", f"/jobs/{job}", None, tok)
    if s["status"] in ("done", "failed"):
        break
    time.sleep(0.5)
assert s["status"] == "done", s
step(f"生成大纲 → {s['result']['chapters']} 章（{time.time()-t:.1f}s，模型 {s['model']}）")

chapters = call("GET", f"/writing/orders/{order['id']}/chapters", None, tok)
step("大纲骨架：" + " / ".join(c["title"] for c in chapters[:3]) + " …")

pay = call("POST", f"/payments/orders/{order['id']}", {"pay_method": "wechat"}, tok)
call("POST", f"/payments/{pay['serial_no']}/confirm", {}, tok)
step(f"支付 {pay['amount_cents']} 分并确认（mock 渠道）")

t = time.time()
for c in chapters:
    r = call("POST", f"/writing/orders/{order['id']}/chapters/{c['node_id']}", {}, tok)
    for _ in range(60):
        s = call("GET", f"/jobs/{r['job_id']}", None, tok)
        if s["status"] in ("done", "failed"):
            break
        time.sleep(0.3)
    assert s["status"] == "done", s
step(f"逐章生成 {len(chapters)} 章完成（{time.time()-t:.1f}s）")

docx = call("POST", f"/writing/orders/{order['id']}/export", {}, tok, raw=True)
path = os.path.join(OUT, "毕业设计.docx")
with open(path, "wb") as f:
    f.write(docx)
with zipfile.ZipFile(path) as z:
    doc = z.read("word/document.xml").decode("utf-8")
    # 注意：z.read 必须在 with 块内调用，块外 zip 已关闭（实测 ValueError:
    # Attempt to use ZIP archive that was already closed）。
    header_hit = any("AI 辅助生成" in z.read(n).decode("utf-8", "ignore")
                     for n in z.namelist() if n.startswith("word/header"))
checks = {
    "AI 参与度披露表": "AI 参与度" in doc,
    "免责声明": "免责" in doc,
    "水印(header)": header_hit,
    "章节标题": chapters[0]["title"] in doc,
}
step(f"导出 DOCX {len(docx)} 字节 → {path}")
for k, v in checks.items():
    step(f"   {k}: {'✓' if v else '✗'}")
assert all(checks.values()), checks

final = call("GET", f"/writing/orders/{order['id']}", None, tok)
step(f"订单终态 status={final['status']}，总耗时 {time.time()-t0:.1f}s")
print("\n演示完成。产物目录：" + OUT)
PY
