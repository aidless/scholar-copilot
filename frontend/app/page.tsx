// 落地页骨架：v0.2 前只做定位说明
export default function Home() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16 space-y-8">
      <h1 className="text-3xl font-bold">学术写作 Copilot，开源、可自部署</h1>
      <p className="text-neutral-600">
        文献真实可溯源 · 引用数字可核查 · AI 参与度透明标记 · 多租户白标 · LLM 可插拔
      </p>
      <div className="grid grid-cols-2 gap-4 text-sm">
        <a href="/editor" className="border rounded-lg p-4 hover:bg-neutral-50">→ 写作台（大纲/逐章辅助）</a>
        <a href="/references" className="border rounded-lg p-4 hover:bg-neutral-50">→ 文献检索与溯源</a>
        <a href="/review" className="border rounded-lg p-4 hover:bg-neutral-50">→ 核查报告（引用/数字）</a>
        <a href="/admin" className="border rounded-lg p-4 hover:bg-neutral-50">→ 管理台（RBAC）</a>
      </div>
    </main>
  );
}
