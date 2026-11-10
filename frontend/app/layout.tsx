// 根布局：导航里刻意没有「代写/过查重」类文案——定位是 Copilot 不是代工
export const metadata = { title: "Scholar Copilot", description: "开源学术写作 Copilot" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-white text-neutral-900 antialiased">
        <nav className="border-b px-6 py-3 flex gap-6 text-sm">
          <a href="/" className="font-semibold">Scholar Copilot</a>
          <a href="/workbench">写作台</a>
          <a href="/references">文献溯源</a>
          <a href="/review">文本体检</a>
          <a href="/ppt">演示与图表</a>
          <a href="/distributor">代理中心</a>
          <a href="/admin" className="text-neutral-400">管理台</a>
        </nav>
        {children}
      </body>
    </html>
  );
}
