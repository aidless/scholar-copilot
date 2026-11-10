// job 进度订阅：把后端 /jobs/{id}/ws 的推送接成 React 状态。
//
// 为什么不用轮询：生成一章动辄 30~60 秒，2 秒轮询一次就是几十个请求，
// 而且状态变化有延迟。后端已提供 WebSocket（终态自动关闭、属主不符 1008 关闭），
// 前端直接订阅即可。
//
// 失败降级：WS 建不起来（反向代理没配 upgrade、浏览器不支持）时自动退回
// 2 秒轮询 /jobs/{id}，保证功能不因传输层挂掉而失效。
"use client";
import { useEffect, useRef, useState } from "react";
import { API_BASE, api, tokenStore } from "./api";

export type JobState = {
  job_id: string;
  kind: string;
  status: "queued" | "running" | "done" | "failed";
  progress: number;
  result: any;
  error: string | null;
};

const TERMINAL = new Set(["done", "failed"]);

function wsUrl(jobId: string, token: string) {
  const base = API_BASE.replace(/^http/, "ws");
  return `${base}/jobs/${jobId}/ws?token=${encodeURIComponent(token)}`;
}

/**
 * 订阅一个 job 的进度。`jobId` 为 null 时不做任何事。
 * 返回最近一次状态、以及是否已到终态。
 */
export function useJobProgress(jobId: string | null) {
  const [state, setState] = useState<JobState | null>(null);
  const [transport, setTransport] = useState<"ws" | "poll" | null>(null);
  const closed = useRef(false);

  useEffect(() => {
    if (!jobId) { setState(null); setTransport(null); return; }
    const token = tokenStore.get();
    if (!token) { setState(null); return; }

    closed.current = false;
    setState(null);

    // 轮询兜底（WS 不可用时）
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    const startPolling = () => {
      if (closed.current) return;
      setTransport("poll");
      const tick = async () => {
        if (closed.current) return;
        try {
          const s = await api<JobState>(`/jobs/${jobId}`);
          if (closed.current) return;
          setState(s);
          if (TERMINAL.has(s.status)) return;
        } catch {
          // 轮询失败就再试一次，不打断用户
        }
        pollTimer = setTimeout(tick, 2000);
      };
      tick();
    };

    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(wsUrl(jobId, token));
      ws.onopen = () => setTransport("ws");
      ws.onmessage = (ev) => {
        try {
          const s = JSON.parse(ev.data) as JobState;
          setState(s);
        } catch {
          /* 单帧解析失败忽略，下一帧继续 */
        }
      };
      ws.onerror = () => { /* onclose 会接手降级 */ };
      ws.onclose = () => {
        // 终态关闭属正常；非终态关闭说明通道有问题 → 退轮询
        setState((prev) => {
          if (!prev || !TERMINAL.has(prev.status)) startPolling();
          return prev;
        });
      };
    } catch {
      startPolling();
    }

    return () => {
      closed.current = true;
      if (pollTimer) clearTimeout(pollTimer);
      if (ws && ws.readyState <= WebSocket.OPEN) ws.close();
    };
  }, [jobId]);

  return { state, transport };
}
