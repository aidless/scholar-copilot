"use client";
// 演示与图表：PPTX 生成（服务端渲染可编辑 PPT）+ 自然语言出 Mermaid 代码
import { useState } from "react";
import { api, tokenStore } from "../../lib/api";

export default function PptPage() {
  const [topic, setTopic] = useState("");
  const [audience, setAudience] = useState("学术评审");
  const [pages, setPages] = useState(10);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const [desc, setDesc] = useState("");
  const [kind, setKind] = useState("flowchart");
  const [mermaid, setMermaid] = useState("");
  const [dErr, setDErr] = useState("");

  async function makePpt() {
    setBusy(true); setErr("");
    try {
      const res = await api<Response>("/tools/ppt", {
        method: "POST", body: { topic, audience, pages }, raw: true,
      });
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `${topic.slice(0, 30) || "演示"}.pptx`; a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  async function makeDiagram() {
    setDErr("");
    try {
      const r = await api<{ mermaid: string }>("/tools/diagram", {
        method: "POST", body: { description: desc, kind },
      });
      setMermaid(r.mermaid);
    } catch (e: any) { setDErr(e.message); }
  }

  if (!tokenStore.get()) return <main className="p-8 text-sm">请先<a className="underline" href="/">登录</a>。</main>;

  return (
    <main className="p-8 max-w-3xl space-y-10">
      <section className="space-y-3">
        <h1 className="text-xl font-semibold">PPT 大纲生成</h1>
        <p className="text-sm text-neutral-500">按主题生成可编辑的 .pptx（结构与要点自动排版，不含装饰模板）。</p>
        <input className="border rounded px-3 py-2 w-full" placeholder="演示主题，如：深度学习在学术写作中的应用"
               value={topic} onChange={(e) => setTopic(e.target.value)} />
        <div className="flex gap-3 text-sm">
          <input className="border rounded px-3 py-2 flex-1" placeholder="听众" value={audience}
                 onChange={(e) => setAudience(e.target.value)} />
          <input className="border rounded px-3 py-2 w-28" type="number" min={4} max={20} value={pages}
                 onChange={(e) => setPages(Number(e.target.value))} />
          <button className="bg-neutral-900 text-white rounded px-4 disabled:opacity-40"
                  disabled={busy || topic.length < 2} onClick={makePpt}>
            {busy ? "生成中…" : "生成并下载"}
          </button>
        </div>
        {err && <p className="text-sm text-red-600">{err}</p>}
      </section>

      <section className="space-y-3">
        <h1 className="text-xl font-semibold">图表（Mermaid）</h1>
        <p className="text-sm text-neutral-500">自然语言描述 → Mermaid 源码。代码可审阅、可入库，不返回黑盒图片。</p>
        <textarea className="border rounded px-3 py-2 w-full h-24" placeholder="如：用户下单 → 生成大纲 → 逐章生成 → 引用核查 → 导出"
                  value={desc} onChange={(e) => setDesc(e.target.value)} />
        <div className="flex gap-3 text-sm">
          <select className="border rounded px-3 py-2" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="flowchart">流程图</option>
            <option value="sequence">时序图</option>
            <option value="architecture">架构图</option>
          </select>
          <button className="border rounded px-4" disabled={desc.length < 4} onClick={makeDiagram}>生成 Mermaid</button>
        </div>
        {dErr && <p className="text-sm text-red-600">{dErr}</p>}
        {mermaid && (
          <pre className="bg-neutral-50 border rounded p-3 text-xs overflow-x-auto whitespace-pre-wrap">{mermaid}</pre>
        )}
      </section>
    </main>
  );
}
