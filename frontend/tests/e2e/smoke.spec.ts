import { test, expect } from "@playwright/test";

// 关键路径冒烟（#13）。不依赖后端：即使接口不可达，页面骨架与表单也应正常渲染。

test("首页渲染品牌与导航，登录表单可见", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("nav a", { hasText: "Scholar Copilot" })).toBeVisible();
  await expect(page.locator("nav a", { hasText: "文献溯源" })).toBeVisible();
  await expect(page.locator('input[placeholder="手机号（11 位）"]')).toBeVisible();
  await expect(page.getByRole("button", { name: "登录", exact: true }).first()).toBeVisible();
});

test("登录/注册切换显示短信验证码输入", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator('input[placeholder="短信验证码（开发模式 000000）"]')).toHaveCount(0);
  await page.getByRole("button", { name: "注册" }).click();
  await expect(page.locator('input[placeholder="短信验证码（开发模式 000000）"]')).toBeVisible();
});

test("文献溯源页加载且标题/搜索框可见", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/references");
  await expect(page.getByRole("heading", { name: "文献检索与溯源" })).toBeVisible();
  await expect(page.locator('input[placeholder*="关键词 / 论文标题"]')).toBeVisible();
  expect(errors, errors.join("\n")).toHaveLength(0);
});
