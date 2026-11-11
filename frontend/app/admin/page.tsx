"use client";
// 管理台：RBAC 登录 → 统计 / 用户 / 订单 / 配额调整 / 审计日志（全部需要 admin token）
import { useCallback, useEffect, useState } from "react";
import { api, tokenStore } from "../../lib/api";

type Stats = { users: number; orders: number; jobs: number; payments_total: number; payments_paid: number; revenue_cents: number };
type UserRow = { id: string; tenant_id: string; phone: string; created_at: string | null };
type OrderRow = { id: string; tenant_id: string; owner_id: string; title: string; education: string; status: string; price_cents: number; paid_at: string | null; created_at: string | null };
type AuditRow = { id: string; admin_id: string; action: string; target: any; detail: any; created_at: string | null };
type Report = { window_days: number; revenue_cents: number; orders_new: number; new_users: number; tokens_in: number; tokens_out: number };
type TenantRow = { id: string; name: string; domain: string; plan: string; status: string; balance_cents: number; created_at: string | null };
type DistributorRow = { id: string; name: string; phone: string; code: string; rate_bps: number; balance_cents: number; status: string; created_at: string | null };
type CommissionRow = { id: string; distributor_id: string; order_id: string; amount_cents: number; status: string; created_at: string | null };
type TransferRow = { id: string; distributor_id: string; amount_cents: number; status: string; note: string; created_at: string | null; paid_at: string | null };

export default function Admin() {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<string | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [orders, setOrders] = useState<OrderRow[]>([]);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [tenants, setTenants] = useState<TenantRow[]>([]);
  const [distributors, setDistributors] = useState<DistributorRow[]>([]);
  const [commissions, setCommissions] = useState<CommissionRow[]>([]);
  const [transfers, setTransfers] = useState<TransferRow[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [s, u, o, a, rp, tn, ds, cm, tf] = await Promise.all([
        api<Stats>("/admin/stats", { admin: true }),
        api<UserRow[]>("/admin/users", { admin: true }),
        api<OrderRow[]>("/admin/orders", { admin: true }),
        api<AuditRow[]>("/admin/audit-log", { admin: true }),
        api<Report>("/admin/reports/summary?days=7", { admin: true }),
        api<TenantRow[]>("/admin/tenants", { admin: true }),
        api<DistributorRow[]>("/admin/distributors", { admin: true }),
        api<CommissionRow[]>("/admin/commissions", { admin: true }),
        api<TransferRow[]>("/admin/distributor-transfers", { admin: true }),
      ]);
      setStats(s); setUsers(u); setOrders(o); setAudit(a); setReport(rp);
      setTenants(tn); setDistributors(ds); setCommissions(cm); setTransfers(tf);
    } catch (err: any) { setMsg(`加载失败：${err.message}`); }
  }, []);

  useEffect(() => { if (tokenStore.adminGet()) { setRole("restored"); reload(); } }, [reload]);

  async function login(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      const r = await api<{ access_token: string; role: string }>("/admin/login", { method: "POST", body: { username, password } });
      tokenStore.adminSet(r.access_token); setRole(r.role);
      await reload();
    } catch (err: any) { setMsg(`登录失败：${err.message}`); } finally { setBusy(false); }
  }

  async function adjustQuota(userId: string) {
    const raw = window.prompt("配额调整量（正数赠送，负数回收）", "1");
    if (!raw) return;
    const delta = Number(raw);
    if (!Number.isInteger(delta) || delta === 0) { setMsg("请输入非零整数"); return; }
    const reason = window.prompt("调整原因（2~200 字，会进审计日志）", "客服补偿") || "";
    try {
      await api("/admin/quota/adjust", { method: "POST", admin: true, body: { user_id: userId, kind: "outline", delta, reason } });
      setMsg(`已为 ${userId} 调整配额 ${delta}`);
      await reload();
    } catch (err: any) { setMsg(`调整失败：${err.message}`); }
  }

  async function createTenant() {
    const name = window.prompt("租户名称（2 字以上）");
    if (!name) return;
    const domain = window.prompt("绑定域名（可空）", "") || "";
    try {
      await api("/admin/tenants", { method: "POST", admin: true, body: { name, domain } });
      setMsg(`已创建租户 ${name}`);
      await reload();
    } catch (err: any) { setMsg(`创建租户失败：${err.message}`); }
  }

  async function createDistributor() {
    const name = window.prompt("分销商名称");
    if (!name) return;
    const phone = window.prompt("联系电话", "13800000000") || "";
    const code = window.prompt("推广码（2~32 字，唯一）");
    if (!code) return;
    const rateRaw = window.prompt("佣金比例（万分比，500 = 5%）", "500") || "500";
    try {
      await api("/admin/distributors", { method: "POST", admin: true,
        body: { name, phone, code, rate_bps: Number(rateRaw), tenant_id: "primary" } });
      setMsg(`已创建分销商 ${name}（推广码 ${code}）`);
      await reload();
    } catch (err: any) { setMsg(`创建分销商失败：${err.message}`); }
  }

  async function settleCommission(id: string) {
    if (!window.confirm("确认结算该笔佣金？（结算后不可撤销）")) return;
    try {
      await api(`/admin/commissions/${id}/settle`, { method: "POST", admin: true });
      setMsg(`佣金 ${id} 已结算`);
      await reload();
    } catch (err: any) { setMsg(`结算失败：${err.message}`); }
  }

  async function auditTransfer(id: string, action: "approve" | "reject") {
    const label = action === "approve" ? "通过" : "驳回";
    if (!window.confirm(`确认${label}提现申请 ${id}？`)) return;
    try {
      await api(`/admin/distributor-transfers/${id}/${action}`, { method: "POST", admin: true });
      setMsg(`提现 ${id} 已${label}`);
      await reload();
    } catch (err: any) { setMsg(`${label}失败：${err.message}`); }
  }

  if (!role) {
    return (
      <main className="mx-auto max-w-md px-6 py-16 space-y-4 text-sm">
        <h1 className="text-2xl font-semibold">管理台登录</h1>
        <form onSubmit={login} className="border rounded-lg p-4 space-y-3">
          <input className="w-full border rounded px-3 py-2" placeholder="管理员账号" value={username} onChange={(e) => setUsername(e.target.value)} required />
          <input className="w-full border rounded px-3 py-2" type="password" placeholder="密码" value={password} onChange={(e) => setPassword(e.target.value)} required />
          <button disabled={busy} className="w-full bg-neutral-900 text-white rounded py-2 disabled:opacity-50">登录</button>
          {msg && <p className="text-xs text-neutral-600">{msg}</p>}
        </form>
        <p className="text-xs text-neutral-400">初始管理员由部署时 SC_ADMIN_INITIAL_PASSWORD 引导创建；无默认口令。</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-6xl px-6 py-10 space-y-8 text-sm">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">管理台</h1>
        <span className="text-xs text-neutral-500">
          角色：{role} · <button className="underline" onClick={() => { tokenStore.adminClear(); setRole(null); }}>退出</button>
        </span>
      </div>
      {msg && <p className="text-xs bg-neutral-50 border rounded p-3">{msg}</p>}

      {stats && (
        <section className="grid grid-cols-2 md:grid-cols-6 gap-3">
          <Card label="用户" value={stats.users} />
          <Card label="订单" value={stats.orders} />
          <Card label="任务" value={stats.jobs} />
          <Card label="支付单" value={stats.payments_total} />
          <Card label="已支付" value={stats.payments_paid} />
          <Card label="营收(元)" value={(stats.revenue_cents / 100).toFixed(2)} />
        </section>
      )}

      <section className="space-y-2">
        <h2 className="font-medium">用户</h2>
        <table className="w-full text-xs border">
          <thead className="bg-neutral-50"><tr><th className="p-2 text-left">ID</th><th className="p-2 text-left">租户</th><th className="p-2 text-left">手机号</th><th className="p-2 text-left">注册时间</th><th className="p-2">操作</th></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-t">
                <td className="p-2 font-mono">{u.id}</td>
                <td className="p-2">{u.tenant_id}</td>
                <td className="p-2">{u.phone}</td>
                <td className="p-2">{u.created_at?.slice(0, 19).replace("T", " ")}</td>
                <td className="p-2 text-center"><button className="border rounded px-2 py-0.5" onClick={() => adjustQuota(u.id)}>调配额</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="space-y-2">
        <h2 className="font-medium">订单</h2>
        <table className="w-full text-xs border">
          <thead className="bg-neutral-50"><tr><th className="p-2 text-left">题目</th><th className="p-2 text-left">层次</th><th className="p-2 text-left">状态</th><th className="p-2 text-left">金额(元)</th><th className="p-2 text-left">支付</th></tr></thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id} className="border-t">
                <td className="p-2">{o.title}</td>
                <td className="p-2">{o.education}</td>
                <td className="p-2">{o.status}</td>
                <td className="p-2">{(o.price_cents / 100).toFixed(2)}</td>
                <td className="p-2">{o.paid_at ? "已支付" : "未支付"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="font-medium">租户</h2>
          <button className="border rounded px-3 py-1 text-xs" onClick={createTenant}>新建租户</button>
        </div>
        <table className="w-full text-xs border">
          <thead className="bg-neutral-50"><tr><th className="p-2 text-left">ID</th><th className="p-2 text-left">名称</th><th className="p-2 text-left">域名</th><th className="p-2 text-left">套餐</th><th className="p-2 text-left">状态</th><th className="p-2 text-left">余额(元)</th></tr></thead>
          <tbody>
            {tenants.length === 0 && <tr><td className="p-2 text-neutral-400" colSpan={6}>暂无租户</td></tr>}
            {tenants.map((t) => (
              <tr key={t.id} className="border-t">
                <td className="p-2 font-mono">{t.id}</td>
                <td className="p-2">{t.name}</td>
                <td className="p-2">{t.domain || "—"}</td>
                <td className="p-2">{t.plan}</td>
                <td className="p-2">{t.status}</td>
                <td className="p-2">{(t.balance_cents / 100).toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="font-medium">分销商</h2>
          <button className="border rounded px-3 py-1 text-xs" onClick={createDistributor}>新建分销商</button>
        </div>
        <table className="w-full text-xs border">
          <thead className="bg-neutral-50"><tr><th className="p-2 text-left">名称</th><th className="p-2 text-left">推广码</th><th className="p-2 text-left">电话</th><th className="p-2 text-left">佣金率</th><th className="p-2 text-left">余额(元)</th><th className="p-2 text-left">状态</th></tr></thead>
          <tbody>
            {distributors.length === 0 && <tr><td className="p-2 text-neutral-400" colSpan={6}>暂无分销商</td></tr>}
            {distributors.map((d) => (
              <tr key={d.id} className="border-t">
                <td className="p-2">{d.name}</td>
                <td className="p-2 font-mono">{d.code}</td>
                <td className="p-2">{d.phone}</td>
                <td className="p-2">{(d.rate_bps / 100).toFixed(2)}%</td>
                <td className="p-2">{(d.balance_cents / 100).toFixed(2)}</td>
                <td className="p-2">{d.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="space-y-2">
        <h2 className="font-medium">佣金</h2>
        <table className="w-full text-xs border">
          <thead className="bg-neutral-50"><tr><th className="p-2 text-left">ID</th><th className="p-2 text-left">分销商</th><th className="p-2 text-left">订单</th><th className="p-2 text-left">金额(元)</th><th className="p-2 text-left">状态</th><th className="p-2">操作</th></tr></thead>
          <tbody>
            {commissions.length === 0 && <tr><td className="p-2 text-neutral-400" colSpan={6}>暂无佣金记录</td></tr>}
            {commissions.map((c) => (
              <tr key={c.id} className="border-t">
                <td className="p-2 font-mono">{c.id}</td>
                <td className="p-2 font-mono">{c.distributor_id}</td>
                <td className="p-2 font-mono">{c.order_id}</td>
                <td className="p-2">{(c.amount_cents / 100).toFixed(2)}</td>
                <td className="p-2">{c.status}</td>
                <td className="p-2 text-center">
                  {c.status === "pending"
                    ? <button className="border rounded px-2 py-0.5" onClick={() => settleCommission(c.id)}>结算</button>
                    : <span className="text-neutral-400">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="space-y-2">
        <h2 className="font-medium">提现审核</h2>
        <table className="w-full text-xs border">
          <thead className="bg-neutral-50"><tr><th className="p-2 text-left">ID</th><th className="p-2 text-left">分销商</th><th className="p-2 text-left">金额(元)</th><th className="p-2 text-left">状态</th><th className="p-2 text-left">备注</th><th className="p-2">操作</th></tr></thead>
          <tbody>
            {transfers.length === 0 && <tr><td className="p-2 text-neutral-400" colSpan={6}>暂无提现申请</td></tr>}
            {transfers.map((t) => (
              <tr key={t.id} className="border-t">
                <td className="p-2 font-mono">{t.id}</td>
                <td className="p-2 font-mono">{t.distributor_id}</td>
                <td className="p-2">{(t.amount_cents / 100).toFixed(2)}</td>
                <td className="p-2">{t.status}</td>
                <td className="p-2">{t.note || "—"}</td>
                <td className="p-2 text-center space-x-1">
                  {t.status === "pending" ? (
                    <>
                      <button className="border rounded px-2 py-0.5" onClick={() => auditTransfer(t.id, "approve")}>通过</button>
                      <button className="border rounded px-2 py-0.5" onClick={() => auditTransfer(t.id, "reject")}>驳回</button>
                    </>
                  ) : <span className="text-neutral-400">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="space-y-2">
        <h2 className="font-medium">对账导出（CSV）</h2>
        <div className="flex gap-2 text-xs">
          {(["orders", "payments", "commissions", "audit"] as const).map((k) => (
            <button key={k} className="border rounded px-3 py-1" onClick={() => downloadCsv(k)}>
              {k}.csv
            </button>
          ))}
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="font-medium">审计日志</h2>
        <ul className="text-xs space-y-1">
          {audit.length === 0 && <li className="text-neutral-400">暂无记录</li>}
          {audit.map((a) => (
            <li key={a.id} className="border rounded p-2">
              <span className="font-mono">{a.created_at?.slice(0, 19).replace("T", " ")}</span> · {a.action} · 目标 {JSON.stringify(a.target)} · {JSON.stringify(a.detail)}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );

  async function downloadCsv(kind: string) {
    const res = await api<Response>(`/admin/exports/${kind}.csv`, { admin: true, raw: true });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${kind}.csv`; a.click();
    URL.revokeObjectURL(url);
  }
}

function Card({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="border rounded p-3">
      <div className="text-xs text-neutral-400">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}
