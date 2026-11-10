"use client";
// 首页：定位说明 + 登录/注册（短信验证码开发模式下用 000000）
import { useEffect, useState } from "react";
import { api, tokenStore } from "../lib/api";

type Mode = "login" | "register";

export default function Home() {
  const [mode, setMode] = useState<Mode>("login");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [logged, setLogged] = useState(false);
  const [wxScene, setWxScene] = useState<string | null>(null);
  const [wxMsg, setWxMsg] = useState<string | null>(null);

  useEffect(() => setLogged(!!tokenStore.get()), []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const body: any = { phone, password };
      if (mode === "register") body.check_code = code;
      const r = await api<{ access_token: string }>(mode === "register" ? "/auth/register" : "/auth/login", {
        method: "POST",
        body,
      });
      tokenStore.set(r.access_token);
      setLogged(true);
      setMsg("已登录，进入写作台 →");
    } catch (err: any) {
      setMsg(`失败：${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function wechatLogin() {
    setWxMsg(null);
    try {
      const r = await api<{ scene: string; mode: string; qr_url: string }>("/auth/wechat/qrcode", { method: "POST" });
      setWxScene(r.scene);
      setWxMsg(r.mode === "dev"
        ? `开发模式：扫码会话 ${r.scene}（可在下方模拟确认）`
        : "请使用微信扫码，完成后自动登录");
      // 轮询（3 秒一次，最多 100 次）
      for (let i = 0; i < 100; i++) {
        await new Promise((res) => setTimeout(res, 3000));
        const s = await api<{ status: string; access_token?: string }>(`/auth/wechat/poll?scene=${r.scene}`);
        if (s.status === "confirmed" && s.access_token) {
          tokenStore.set(s.access_token);
          setLogged(true);
          setWxMsg("扫码登录成功");
          return;
        }
      }
    } catch (err: any) { setWxMsg(`失败：${err.message}`); }
  }

  async function mockApprove() {
    if (!wxScene) return;
    try {
      await api("/auth/wechat/mock-approve", { method: "POST", body: { scene: wxScene, phone } });
      setWxMsg("已模拟确认，正在取 token…");
    } catch (err: any) { setWxMsg(`失败：${err.message}`); }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-12 space-y-10">
      <section className="space-y-3">
        <h1 className="text-3xl font-bold">学术写作 Copilot，开源、可自部署</h1>
        <p className="text-neutral-600">
          文献真实可溯源 · 引用可核查 · AI 参与度透明标记 · 多租户白标 · LLM 可插拔
        </p>
        <p className="text-xs text-neutral-400">
          我们不做「代写/包过查重」。产出物带不可关闭的 AI 参与度披露表、水印与免责声明。
        </p>
      </section>

      {logged ? (
        <div className="border rounded-lg p-4 text-sm flex items-center justify-between">
          <span>已登录</span>
          <span className="flex gap-3">
            <a className="underline" href="/workbench">进入写作台</a>
            <button className="underline text-neutral-500" onClick={() => { tokenStore.clear(); setLogged(false); }}>
              退出
            </button>
          </span>
        </div>
      ) : (
        <form onSubmit={submit} className="border rounded-lg p-4 space-y-3 max-w-md">
          <div className="flex gap-2 text-sm">
            <button type="button" onClick={() => setMode("login")}
              className={`px-3 py-1 rounded ${mode === "login" ? "bg-neutral-900 text-white" : "border"}`}>登录</button>
            <button type="button" onClick={() => setMode("register")}
              className={`px-3 py-1 rounded ${mode === "register" ? "bg-neutral-900 text-white" : "border"}`}>注册</button>
          </div>
          <input className="w-full border rounded px-3 py-2 text-sm" placeholder="手机号（11 位）"
            value={phone} onChange={(e) => setPhone(e.target.value)} required />
          <input className="w-full border rounded px-3 py-2 text-sm" type="password" placeholder="密码（至少 8 位）"
            value={password} onChange={(e) => setPassword(e.target.value)} required />
          {mode === "register" && (
            <input className="w-full border rounded px-3 py-2 text-sm" placeholder="短信验证码（开发模式 000000）"
              value={code} onChange={(e) => setCode(e.target.value)} required />
          )}
          <button type="button" onClick={wechatLogin}
            className="w-full border rounded py-2 text-sm">微信扫码登录</button>
          <button disabled={busy} className="w-full bg-neutral-900 text-white rounded py-2 text-sm disabled:opacity-50">
            {busy ? "处理中…" : mode === "register" ? "注册并登录" : "登录"}
          </button>
          {msg && <p className="text-xs text-neutral-600">{msg}</p>}
        </form>
      )}

      {wxMsg && (
        <div className="border rounded-lg p-4 text-sm space-y-2 max-w-md">
          <p>{wxMsg}</p>
          {wxScene && (
            <div className="flex gap-2">
              <input className="border rounded px-3 py-1 text-xs flex-1" placeholder="手机号（dev 模拟确认用）"
                value={phone} onChange={(e) => setPhone(e.target.value)} />
              <button className="border rounded px-3 py-1 text-xs" onClick={mockApprove}>模拟扫码确认（dev）</button>
            </div>
          )}
        </div>
      )}

      <section className="grid grid-cols-2 gap-4 text-sm">
        <a href="/workbench" className="border rounded-lg p-4 hover:bg-neutral-50">→ 写作台（下单/大纲/逐章/改稿/支付/导出）</a>
        <a href="/references" className="border rounded-lg p-4 hover:bg-neutral-50">→ 文献检索与溯源核查</a>
        <a href="/review" className="border rounded-lg p-4 hover:bg-neutral-50">→ AI 味体检（启发式）</a>
        <a href="/admin" className="border rounded-lg p-4 hover:bg-neutral-50">→ 管理台（RBAC/配额/审计）</a>
      </section>
    </main>
  );
}
