"use client";
// 写作台：下单 → 免费大纲 → 逐章生成 → 在线改稿 → 支付 → 导出 DOCX
import { useCallback, useEffect, useState } from "react";
import { api, tokenStore } from "../../lib/api";

type Order = {
  id: string; title: string; education: string; word_count: number;
  status: string; price_cents: number; created_at: string | null;
};
type Chapter = {
  id: string; node_id: string; idx: number; title: string; description: string | null;
  status: string; word_count: number; ai_level: string; content_md: string | null;
};

const EDU = ["本科", "硕士", "博士"];
const STATUS_ZH: Record<string, string> = {
  draft: "草稿", outlining: "大纲生成中", outline_done: "大纲完成", writing: "正文生成中",
  writing_done: "正文完成", exported: "已导出", paid: "已支付",
};
const AI_ZH: Record<string, string> = { A: "A·AI生成未修改", B: "B·AI初稿已修改", C: "C·人工撰写" };

export default function Workbench() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [cur, setCur] = useState<Order | null>(null);
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [title, setTitle] = useState("");
  const [education, setEducation] = useState("本科");
  const [words, setWords] = useState(12000);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadOrders = useCallback(async () => {
    try {
      const r = await api<Order[]>("/writing/orders");
      setOrders(r);
    } catch (e: any) { setMsg(`加载订单失败：${e.message}`); }
  }, []);

  const loadChapters = useCallback(async (orderId: string) => {
    try { setChapters(await api<Chapter[]>(`/writing/orders/${orderId}/chapters`)); }
    catch (e: any) { setMsg(`加载章节失败：${e.message}`); }
  }, []);

  useEffect(() => { if (!tokenStore.get()) { setMsg("请先在首页登录"); return; } loadOrders(); }, [loadOrders]);

  async function createOrder(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      const o = await api<Order>("/writing/orders", { method: "POST", body: { title, education, word_count: words } });
      setMsg(`已建单：${o.title}，服务端计价 ${(o.price_cents / 100).toFixed(2)} 元`);
      setTitle("");
      await loadOrders();
      setCur(o); setChapters([]);
    } catch (err: any) { setMsg(`建单失败：${err.message}`); } finally { setBusy(false); }
  }

  async function genOutline() {
    if (!cur) return;
    setBusy(true); setMsg("大纲生成中（免费额度，真模型约 30~60 秒）…");
    try {
      await api(`/writing/orders/${cur.id}/outline?wait=true`, { method: "POST", body: { feedback: null } });
      await loadChapters(cur.id);
      const fresh = await api<Order>(`/writing/orders/${cur.id}`);
      setCur(fresh); setMsg("大纲完成，已生成章节骨架");
      await loadOrders();
    } catch (err: any) { setMsg(`大纲失败：${err.message}`); } finally { setBusy(false); }
  }

  async function genChapter(nodeId: string) {
    if (!cur) return;
    setBusy(true); setMsg(`章节 ${nodeId} 生成中…（需先支付）`);
    try {
      await api(`/writing/orders/${cur.id}/chapters/${nodeId}?wait=true`, { method: "POST" });
      await loadChapters(cur.id); setMsg(`章节 ${nodeId} 完成`);
    } catch (err: any) { setMsg(`生成失败：${err.message}`); } finally { setBusy(false); }
  }

  async function saveChapter(ch: Chapter, content: string) {
    if (!cur) return;
    setBusy(true);
    try {
      await api(`/writing/orders/${cur.id}/chapters/${ch.node_id}`, { method: "PUT", body: { content_md: content } });
      await loadChapters(cur.id); setMsg(`已保存 ${ch.node_id}（人工修改 → AI 参与度如实上调）`);
    } catch (err: any) { setMsg(`保存失败：${err.message}`); } finally { setBusy(false); }
  }

  async function rewriteChapter(ch: Chapter) {
    if (!cur) return;
    setBusy(true); setMsg(`降重改写 ${ch.node_id} 中…`);
    try {
      await api(`/writing/orders/${cur.id}/chapters/${ch.node_id}/rewrite?wait=true`, {
        method: "POST", body: { instruction: "语言更学术、降低重复表达，保留全部事实与引用标记" },
      });
      await loadChapters(cur.id); setMsg(`${ch.node_id} 改写完成`);
    } catch (err: any) { setMsg(`改写失败：${err.message}`); } finally { setBusy(false); }
  }

  async function pay() {
    if (!cur) return;
    setBusy(true);
    try {
      const p = await api<{ serial_no: string; amount_cents: number }>(`/payments/orders/${cur.id}`, {
        method: "POST", body: { pay_method: "wechat" },
      });
      await api(`/payments/${p.serial_no}/confirm`, { method: "POST" });
      const fresh = await api<Order>(`/writing/orders/${cur.id}`);
      setCur(fresh); setMsg(`支付成功（mock 模式）：${(p.amount_cents / 100).toFixed(2)} 元，正文生成已解锁`);
    } catch (err: any) { setMsg(`支付失败：${err.message}`); } finally { setBusy(false); }
  }

  async function exportDocx() {
    if (!cur) return;
    setBusy(true);
    try {
      const res = await api<Response>(`/writing/orders/${cur.id}/export`, { method: "POST", raw: true });
      const blob = await (res as unknown as Response).blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${cur.title || "thesis"}.docx`;
      a.click();
      URL.revokeObjectURL(a.href);
      setMsg("已下载 DOCX（含水印/AI 参与度披露表/免责声明）");
      await loadOrders();
    } catch (err: any) { setMsg(`导出失败：${err.message}`); } finally { setBusy(false); }
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-10 space-y-8 text-sm">
      <h1 className="text-2xl font-semibold">写作台</h1>

      <form onSubmit={createOrder} className="border rounded-lg p-4 grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
        <label className="space-y-1 md:col-span-2">题目
          <input className="w-full border rounded px-3 py-2" value={title} onChange={(e) => setTitle(e.target.value)} required />
        </label>
        <label className="space-y-1">层次
          <select className="w-full border rounded px-3 py-2" value={education} onChange={(e) => setEducation(e.target.value)}>
            {EDU.map((x) => <option key={x}>{x}</option>)}
          </select>
        </label>
        <label className="space-y-1">目标字数
          <input type="number" min={3000} step={1000} className="w-full border rounded px-3 py-2"
            value={words} onChange={(e) => setWords(Number(e.target.value))} />
        </label>
        <button disabled={busy} className="bg-neutral-900 text-white rounded py-2 md:col-span-4 disabled:opacity-50">下单（价格服务端计算）</button>
      </form>

      {msg && <p className="text-xs bg-neutral-50 border rounded p-3 whitespace-pre-wrap">{msg}</p>}

      <section className="grid md:grid-cols-3 gap-6">
        <div className="md:col-span-1 space-y-2">
          <h2 className="font-medium">我的订单</h2>
          {orders.length === 0 && <p className="text-neutral-400">暂无订单</p>}
          {orders.map((o) => (
            <button key={o.id} onClick={() => { setCur(o); loadChapters(o.id); }}
              className={`w-full text-left border rounded p-3 hover:bg-neutral-50 ${cur?.id === o.id ? "border-neutral-900" : ""}`}>
              <div className="font-medium">{o.title}</div>
              <div className="text-xs text-neutral-500">{o.education} · {o.word_count} 字 · {(o.price_cents / 100).toFixed(2)} 元</div>
              <div className="text-xs text-neutral-400">{STATUS_ZH[o.status] || o.status}</div>
            </button>
          ))}
        </div>

        <div className="md:col-span-2 space-y-3">
          {!cur && <p className="text-neutral-400">选择左侧订单开始</p>}
          {cur && (
            <>
              <div className="flex flex-wrap gap-2 items-center">
                <span className="font-medium">{cur.title}</span>
                <span className="text-xs text-neutral-500">{STATUS_ZH[cur.status] || cur.status}</span>
                <button disabled={busy} onClick={genOutline} className="border rounded px-3 py-1 disabled:opacity-50">生成大纲（免费 3 次）</button>
                <button disabled={busy} onClick={pay} className="border rounded px-3 py-1 disabled:opacity-50">支付（mock）</button>
                <button disabled={busy} onClick={exportDocx} className="border rounded px-3 py-1 disabled:opacity-50">导出 DOCX</button>
              </div>

              {chapters.map((ch) => (
                <details key={ch.id} className="border rounded p-3">
                  <summary className="cursor-pointer flex flex-wrap gap-2 items-center">
                    <span className="font-medium">{ch.idx}. {ch.title}</span>
                    <span className="text-xs text-neutral-500">{ch.status} · {ch.word_count} 字</span>
                    {ch.content_md && <span className="text-xs text-neutral-400">{AI_ZH[ch.ai_level] || ch.ai_level}</span>}
                  </summary>
                  <div className="mt-3 space-y-2">
                    <div className="flex gap-2">
                      <button disabled={busy} onClick={() => genChapter(ch.node_id)} className="border rounded px-3 py-1 disabled:opacity-50">
                        {ch.status === "done" ? "重新生成" : "生成本章"}
                      </button>
                      <button disabled={busy || !ch.content_md} onClick={() => rewriteChapter(ch)} className="border rounded px-3 py-1 disabled:opacity-50">降重改写</button>
                    </div>
                    <ChapterEditor ch={ch} onSave={(text) => saveChapter(ch, text)} busy={busy} />
                  </div>
                </details>
              ))}
            </>
          )}
        </div>
      </section>
    </main>
  );
}

function ChapterEditor({ ch, onSave, busy }: { ch: Chapter; onSave: (t: string) => void; busy: boolean }) {
  const [text, setText] = useState(ch.content_md || "");
  useEffect(() => { setText(ch.content_md || ""); }, [ch.content_md, ch.node_id]);
  return (
    <div className="space-y-2">
      <textarea className="w-full border rounded p-2 h-56 font-mono text-xs" value={text} onChange={(e) => setText(e.target.value)}
        placeholder="本章正文（Markdown）" />
      <button disabled={busy || !text.trim()} onClick={() => onSave(text)} className="border rounded px-3 py-1 disabled:opacity-50">保存修改</button>
    </div>
  );
}
