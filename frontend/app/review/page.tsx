"use client";
// 文本体检 + 降重改写：可测量特征（客观数字）+ 启发式建议（明确不冒充查重率/AIGC 检测率）
import { useState } from "react";
import { api } from "../../lib/api";

type Report = {
  metrics: {
    cjk_chars: number; sentences: number; avg_sentence_len: number; long_sentences: number;
    citation_markers: number; citations_per_1000: number; has_table: boolean;
  };
  cliche: { hits: Record<string, number>; per_1000: number };
  repeats: { gram: string; count: number }[];
  advice: string[];
  disclaimer: string;
};

export default function Review() {
  const [text, setText] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [rewritten, setRewritten] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("语言更学术、减少重复表达，保留全部事实与引用标记");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function detect() {
    setBusy(true); setMsg(null); setRewritten(null);
    try { setReport(await api<Report>("/tools/detect", { method: "POST", body: { text } })); }
    catch (err: any) { setMsg(`体检失败：${err.message}`); } finally { setBusy(false); }
  }

  async function rewrite() {
    setBusy(true); setMsg("改写中…（真模型约 30~90 秒）");
    try {
      const r = await api<{ text: string; tokens_in: number; tokens_out: number }>("/tools/rewrite", {
        method: "POST", body: { text, instruction },
      });
      setRewritten(r.text);
      setMsg(`改写完成：tokens ${r.tokens_in} → ${r.tokens_out}`);
    } catch (err: any) { setMsg(`改写失败：${err.message}`); } finally { setBusy(false); }
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-10 space-y-6 text-sm">
      <h1 className="text-2xl font-semibold">文本体检 / 降重改写</h1>
      <p className="text-neutral-500">体检只报可测量特征（字数、句长、引用标记、重复片段、套话密度），不做「能否过查重」的承诺。</p>

      <textarea className="w-full border rounded p-3 h-48 font-mono text-xs" placeholder="粘贴需要体检/改写的段落（>=10 字）"
        value={text} onChange={(e) => setText(e.target.value)} />

      <div className="flex flex-wrap gap-2 items-center">
        <button disabled={busy || text.trim().length < 10} onClick={detect} className="bg-neutral-900 text-white rounded px-4 py-2 disabled:opacity-50">体检</button>
        <input className="flex-1 min-w-64 border rounded px-3 py-2" value={instruction} onChange={(e) => setInstruction(e.target.value)} placeholder="改写要求" />
        <button disabled={busy || text.trim().length < 10} onClick={rewrite} className="border rounded px-4 py-2 disabled:opacity-50">降重改写</button>
      </div>

      {msg && <p className="text-xs bg-neutral-50 border rounded p-3">{msg}</p>}

      {report && (
        <section className="border rounded p-4 space-y-3">
          <h2 className="font-medium">体检报告</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            <Metric label="汉字数" value={report.metrics.cjk_chars} />
            <Metric label="句子数" value={report.metrics.sentences} />
            <Metric label="平均句长" value={report.metrics.avg_sentence_len} />
            <Metric label="超长句(>120)" value={report.metrics.long_sentences} />
            <Metric label="引用标记 [N]" value={report.metrics.citation_markers} />
            <Metric label="每千字引用" value={report.metrics.citations_per_1000} />
            <Metric label="含表格" value={report.metrics.has_table ? "是" : "否"} />
            <Metric label="套话密度/千字" value={report.cliche.per_1000} />
          </div>
          {Object.keys(report.cliche.hits).length > 0 && (
            <p className="text-xs text-neutral-600">命中套话：{Object.entries(report.cliche.hits).map(([k, v]) => `${k}×${v}`).join("，")}</p>
          )}
          {report.repeats.length > 0 && (
            <p className="text-xs text-neutral-600">重复片段：{report.repeats.map((r) => `「${r.gram.slice(0, 12)}…」×${r.count}`).join("；")}</p>
          )}
          <ul className="text-xs list-disc pl-5 space-y-1">
            {report.advice.length === 0 ? <li>未发现明显可改进项</li> : report.advice.map((a) => <li key={a}>{a}</li>)}
          </ul>
          <p className="text-xs text-neutral-400">{report.disclaimer}</p>
        </section>
      )}

      {rewritten && (
        <section className="border rounded p-4 space-y-2">
          <h2 className="font-medium">改写结果</h2>
          <textarea className="w-full border rounded p-3 h-56 font-mono text-xs" value={rewritten} readOnly />
          <button className="border rounded px-3 py-1 text-xs" onClick={() => navigator.clipboard.writeText(rewritten)}>复制</button>
        </section>
      )}
    </main>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="border rounded p-2">
      <div className="text-neutral-400">{label}</div>
      <div className="text-base font-medium">{value}</div>
    </div>
  );
}
