"use client";
// 文献：真实检索（OpenAlex/Crossref）+ 单条引用三态核查（verified/suspicious/fake）
import { useState } from "react";
import { api, tokenStore } from "../../lib/api";

type Hit = {
  title: string; authors: string[]; year: number | null; doi: string | null;
  url: string | null; venue: string | null; cited_by: number; source: string;
};
type Verdict = { state: string; similarity: number; evidence: any };

const STATE_ZH: Record<string, string> = {
  verified: "✅ 已核实", suspicious: "⚠️ 存疑", fake: "❌ 疑似不存在", unverified: "未核查",
};

export default function References() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [source, setSource] = useState<string | null>(null);
  const [verdicts, setVerdicts] = useState<Record<string, Verdict>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function search(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      const r = await api<{ results: Hit[]; source: string }>(`/references/search?q=${encodeURIComponent(q)}&limit=8`);
      setHits(r.results); setSource(r.source); setVerdicts({});
      if (r.results.length === 0) setMsg("没有检索到结果，换个关键词试试");
    } catch (err: any) { setMsg(`检索失败：${err.message}`); } finally { setBusy(false); }
  }

  async function verifyAll() {
    setBusy(true); setMsg("核查中（Crossref 逐条比对，可能需要几十秒）…");
    try {
      const r = await api<{ results: (Verdict & { title: string })[] }>("/references/verify", {
        method: "POST",
        body: { items: hits.map((h) => ({ title: h.title, doi: h.doi, year: h.year })) },
      });
      const map: Record<string, Verdict> = {};
      r.results.forEach((x, i) => { const key = hits[i]?.doi || hits[i]?.title || String(i); map[key] = x; });
      setVerdicts(map);
      setMsg("核查完成（三态：verified / suspicious / fake）");
    } catch (err: any) { setMsg(`核查失败：${err.message}`); } finally { setBusy(false); }
  }

  async function attach(hit: Hit, orderId: string) {
    if (!tokenStore.get()) { setMsg("请先登录再挂到订单"); return; }
    try {
      await api(`/references/orders/${orderId}`, {
        method: "POST",
        body: { items: [{ title: hit.title, authors: hit.authors, year: hit.year, doi: hit.doi, url: hit.url, cited_by: hit.cited_by }] },
      });
      setMsg(`已挂到订单 ${orderId}`);
    } catch (err: any) { setMsg(`挂单失败：${err.message}`); }
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-10 space-y-6 text-sm">
      <h1 className="text-2xl font-semibold">文献检索与溯源</h1>
      <p className="text-neutral-500">结果来自真实数据库（DOI 可点开复核）；核查分三态，绝不把「像」当成「是」。</p>

      <form onSubmit={search} className="flex gap-2">
        <input className="flex-1 border rounded px-3 py-2" placeholder="关键词 / 论文标题，如 transformer 综述"
          value={q} onChange={(e) => setQ(e.target.value)} required minLength={2} />
        <button disabled={busy} className="bg-neutral-900 text-white rounded px-4 disabled:opacity-50">检索</button>
        <button type="button" disabled={busy || hits.length === 0} onClick={verifyAll}
          className="border rounded px-4 disabled:opacity-50">核查全部</button>
      </form>

      {msg && <p className="text-xs bg-neutral-50 border rounded p-3">{msg}</p>}
      {source && <p className="text-xs text-neutral-400">数据源：{source}</p>}

      <ul className="space-y-3">
        {hits.map((h) => {
          const key = h.doi || h.title;
          const v = verdicts[key];
          return (
            <li key={key} className="border rounded p-4 space-y-1">
              <div className="font-medium">{h.title}</div>
              <div className="text-xs text-neutral-500">
                {h.authors.slice(0, 4).join("；")}{h.authors.length > 4 ? " 等" : ""} · {h.year ?? "年份未知"} · {h.venue ?? "—"} · 被引 {h.cited_by}
              </div>
              <div className="text-xs flex flex-wrap gap-3 items-center">
                {h.doi && <a className="underline" href={`https://doi.org/${h.doi}`} target="_blank" rel="noreferrer">DOI: {h.doi}</a>}
                {v && <span>{STATE_ZH[v.state] || v.state}（相似度 {v.similarity}）</span>}
                {v?.evidence?.matched_title && <span className="text-neutral-400">匹配到：{v.evidence.matched_title}</span>}
                <AttachInline onAttach={(orderId) => attach(h, orderId)} />
              </div>
            </li>
          );
        })}
      </ul>
    </main>
  );
}

function AttachInline({ onAttach }: { onAttach: (orderId: string) => void }) {
  const [orderId, setOrderId] = useState("");
  return (
    <span className="flex gap-1 items-center">
      <input className="border rounded px-2 py-0.5 w-40 text-xs" placeholder="订单 ID（可选）"
        value={orderId} onChange={(e) => setOrderId(e.target.value)} />
      <button className="border rounded px-2 py-0.5 text-xs" disabled={!orderId} onClick={() => onAttach(orderId)}>挂到订单</button>
    </span>
  );
}
