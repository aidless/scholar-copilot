// 极简 API 客户端：token 存 localStorage，统一错误抛出（含后端中文 detail）
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const TOKEN_KEY = "sc_token";
const ADMIN_KEY = "sc_admin_token";

export const tokenStore = {
  get: () => (typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY)),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
  adminGet: () => (typeof window === "undefined" ? null : localStorage.getItem(ADMIN_KEY)),
  adminSet: (t: string) => localStorage.setItem(ADMIN_KEY, t),
  adminClear: () => localStorage.removeItem(ADMIN_KEY),
};

type Options = {
  method?: string;
  body?: unknown;
  admin?: boolean;
  raw?: boolean; // 返回 Response（下载用）
};

export async function api<T = any>(path: string, opts: Options = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const token = opts.admin ? tokenStore.adminGet() : tokenStore.get();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, {
    method: opts.method || "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });

  if (opts.raw) {
    if (!res.ok) throw new ApiError(res.status, await res.text());
    return res as unknown as T;
  }
  const text = await res.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    if (res.status === 401 && !opts.admin) tokenStore.clear();
    const detail = data && typeof data === "object" ? data.detail : data;
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data as T;
}
