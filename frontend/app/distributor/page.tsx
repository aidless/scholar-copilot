"use client";
// 代理中心：推广码登录 → 佣金台账 → 申请提现（提现由平台审核放款，全程可审计）
import { useEffect, useState } from "react";
import { API_BASE } from "../../lib/api";

const KEY = "sc_dist_token";

async function req<T>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const t = typeof window === "undefined" ? null : localStorage.getItem(KEY);
  if (t) headers["Authorization"] = `Bearer ${t}`;
  const res = await fetch(`${API_BASE}${path}`, {
    method: opts.method || "GET", headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new Error(data?.detail || "请求失败");
  return data as T;
}

export default function DistributorPage() {
  const [code, setCode] = useState("");
  const [phone, setPhone] = useState("");
  const [me, setMe] = useState<any>(null);
  const [commissions, setCommissions] = useState<any[]>([]);
  const [transfers, setTransfers] = useState<any[]>([]);
  const [amount, setAmount] = useState(0);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  async function refresh() {
    try {
      setMe(await req("/distributor/me"));
      setCommissions(await req("/distributor/commissions"));
      setTransfers(await req("/distributor/transfers"));
    } catch (e: any) { setErr(e.message); }
  }

  useEffect(() => {
    if (typeof window !== "undefined" && localStorage.getItem(KEY)) refresh();
  }, []);

  async function login() {
    setErr(""); setMsg("");
    try {
      const r = await req<{ access_token: string }>("/distributor/login", { method: "POST", body: { code, phone } });
      localStorage.setItem(KEY, r.access_token);
      await refresh();
    } catch (e: any) { setErr(e.message); }
  }

  async function withdraw() {
    setErr(""); setMsg("");
    try {
      await req("/distributor/transfers", { method: "POST", body: { amount_cents: amount } });
      setMsg("提现申请已提交，等待平台审核");
      await refresh();
    } catch (e: any) { setErr(e.message); }
  }

  if (!me) {
    return (
      <main className="p-8 max-w-md space-y-3">
        <h1 className="text-xl font-semibold">代理登录</h1>
        <p className="text-sm text-neutral-500">用平台发放的推广码与预留手机号登录。</p>
        <input className="border rounded px-3 py-2 w-full" placeholder="推广码" value={code} onChange={(e) => setCode(e.target.value)} />
        <input className="border rounded px-3 py-2 w-full" placeholder="手机号" value={phone} onChange={(e) => setPhone(e.target.value)} />
        <button className="bg-neutral-900 text-white rounded px-4 py-2" onClick={login}>登录</button>
        {err && <p className="text-sm text-red-600">{err}</p>}
      </main>
    );
  }

  return (
    <main className="p-8 max-w-3xl space-y-6 text-sm">
      <h1 className="text-xl font-semibold">代理中心 · {me.name}（{me.code}）</h1>
      <ul className="grid grid-cols-2 gap-3">
        <li className="border rounded p-3">佣金率：{(me.rate_bps / 100).toFixed(2)}%</li>
        <li className="border rounded p-3">已结算：{(me.commission_settled_cents / 100).toFixed(2)} 元</li>
        <li className="border rounded p-3">待结算：{(me.commission_pending_cents / 100).toFixed(2)} 元</li>
        <li className="border rounded p-3">可提现：{(me.withdrawable_cents / 100).toFixed(2)} 元</li>
      </ul>

      <section className="space-y-2">
        <h2 className="font-medium">申请提现（分）</h2>
        <div className="flex gap-2">
          <input className="border rounded px-3 py-2 w-40" type="number" min={1} value={amount}
                 onChange={(e) => setAmount(Number(e.target.value))} />
          <button className="border rounded px-4" onClick={withdraw}>提交申请</button>
        </div>
        {msg && <p className="text-green-700">{msg}</p>}
        {err && <p className="text-red-600">{err}</p>}
      </section>

      <section>
        <h2 className="font-medium mb-2">佣金明细</h2>
        <table className="w-full text-xs border">
          <thead className="bg-neutral-50"><tr><th className="p-2 text-left">订单</th><th>订单额</th><th>佣金</th><th>状态</th></tr></thead>
          <tbody>
            {commissions.map((c) => (
              <tr key={c.id} className="border-t">
                <td className="p-2">{c.order_id.slice(0, 8)}…</td>
                <td className="text-center">{(c.order_amount_cents / 100).toFixed(2)}</td>
                <td className="text-center">{(c.amount_cents / 100).toFixed(2)}</td>
                <td className="text-center">{c.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2 className="font-medium mb-2">提现记录</h2>
        <ul className="space-y-1 text-xs">
          {transfers.map((t) => (
            <li key={t.id} className="border rounded p-2">
              {(t.amount_cents / 100).toFixed(2)} 元 · {t.status} · {t.created_at?.slice(0, 19)}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
