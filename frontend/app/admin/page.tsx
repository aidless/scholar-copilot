// admin 页骨架：接口点亮前显示占位。对应后端 /admin 路由组。
export default function Page() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="text-2xl font-semibold mb-4">admin</h1>
      <p className="text-neutral-500">v0.x 待实现——见仓库 docs/PORTING.md 的移植清单。</p>
    </main>
  );
}
