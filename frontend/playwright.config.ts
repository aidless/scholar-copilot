import { defineConfig, devices } from "@playwright/test";

// 前端 E2E（v1.9 #13）：对构建后的 Next 应用跑关键路径冒烟。
// 本地用系统 Chrome（PW_CHANNEL=chrome）免下载浏览器；CI 用 `npx playwright install` 的 chromium。
const PORT = process.env.PW_PORT ? Number(process.env.PW_PORT) : 3100;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: true,
  reporter: process.env.CI ? "line" : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    channel: (process.env.PW_CHANNEL as any) || undefined,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npm run start -- -p ${PORT}`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 90_000,
  },
});
