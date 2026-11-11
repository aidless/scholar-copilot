"use client";
// 前端最小 i18n（v1.12 #15）：只覆盖界面骨架文案，不做路由级语言前缀。
// 为什么不做 next-intl 全量改造：本项目是单仓自部署工具，用户群基本中文；
// 真正需要双语的是「生成的正文」与「外发文案」，那部分在 backend/app/i18n.py。
import { useEffect, useState } from "react";

export type Lang = "zh" | "en";

const DICT = {
  zh: {
    "app.name": "Scholar Copilot",
    "nav.workbench": "写作台",
    "nav.references": "文献溯源",
    "nav.review": "文本体检",
    "nav.ppt": "演示与图表",
    "nav.distributor": "代理中心",
    "nav.admin": "管理台",
    "home.tagline": "学术写作 Copilot：大纲、逐章生成、引用核查、成稿导出。",
    "home.login": "登录",
    "home.register": "注册",
    "common.lang": "语言",
  },
  en: {
    "app.name": "Scholar Copilot",
    "nav.workbench": "Workbench",
    "nav.references": "References",
    "nav.review": "Review",
    "nav.ppt": "Slides & Charts",
    "nav.distributor": "Referrals",
    "nav.admin": "Admin",
    "home.tagline": "Academic writing copilot: outline, chapter drafting, citation checks, export.",
    "home.login": "Sign in",
    "home.register": "Sign up",
    "common.lang": "Language",
  },
} as const;

type Key = keyof typeof DICT.zh;
const STORAGE_KEY = "sc-lang";

export function translate(lang: Lang, key: Key): string {
  return DICT[lang]?.[key] ?? DICT.zh[key] ?? key;
}

/** 语言偏好（localStorage 持久化；首屏默认中文，避免水合不一致）。 */
export function useLang(): [Lang, (next: Lang) => void] {
  const [lang, setLang] = useState<Lang>("zh");
  useEffect(() => {
    const saved = (typeof window !== "undefined" && window.localStorage.getItem(STORAGE_KEY)) as Lang | null;
    if (saved === "zh" || saved === "en") setLang(saved);
  }, []);
  function change(next: Lang) {
    setLang(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* 隐私模式下写不进去，忽略即可 */
    }
  }
  return [lang, change];
}

export function useT() {
  const [lang, setLang] = useLang();
  return { lang, setLang, t: (key: Key) => translate(lang, key) };
}
