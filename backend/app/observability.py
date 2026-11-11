"""可观测性：Prometheus 文本指标 + 请求追踪 + 结构化日志（零第三方依赖）。

为什么不引 prometheus_client：本项目要走「clone 即跑」，少一个依赖少一个坑；
Prometheus 文本暴露格式本身很简单（`# TYPE` + `name{labels} value`），手写可控、可单测。
指标刻意压低基数（path 用路由模板而非原始 URL，防止 path 参数炸出百万序列）。
"""
from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from collections import defaultdict
from threading import Lock

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self.requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self.duration_sum: dict[tuple[str, str], float] = defaultdict(float)
        self.duration_count: dict[tuple[str, str], int] = defaultdict(int)
        self.llm_tokens: dict[tuple[str, str], int] = defaultdict(int)  # (kind, direction)
        self.job_status: dict[str, int] = defaultdict(int)

    def observe_request(self, method: str, path: str, status: int, seconds: float) -> None:
        with self._lock:
            self.requests[(method, path, status)] += 1
            self.duration_sum[(method, path)] += seconds
            self.duration_count[(method, path)] += 1

    def observe_tokens(self, kind: str, tokens_in: int, tokens_out: int) -> None:
        with self._lock:
            self.llm_tokens[(kind, "in")] += max(int(tokens_in or 0), 0)
            self.llm_tokens[(kind, "out")] += max(int(tokens_out or 0), 0)

    def set_job_status(self, status: str, count: int) -> None:
        with self._lock:
            self.job_status[status] = count

    def reset(self) -> None:
        with self._lock:
            self.requests.clear()
            self.duration_sum.clear()
            self.duration_count.clear()
            self.llm_tokens.clear()
            self.job_status.clear()

    @staticmethod
    def _esc(v: str) -> str:
        return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    def render(self) -> str:
        out: list[str] = []
        with self._lock:
            out.append("# HELP http_requests_total Total HTTP requests.")
            out.append("# TYPE http_requests_total counter")
            for (method, path, status), n in sorted(self.requests.items()):
                out.append(f'http_requests_total{{method="{self._esc(method)}",'
                           f'path="{self._esc(path)}",status="{status}"}} {n}')

            out.append("# HELP http_request_duration_seconds_sum Sum of request durations.")
            out.append("# TYPE http_request_duration_seconds_sum counter")
            for (method, path), s in sorted(self.duration_sum.items()):
                out.append(f'http_request_duration_seconds_sum{{method="{self._esc(method)}",'
                           f'path="{self._esc(path)}"}} {s:.6f}')

            out.append("# HELP http_request_duration_seconds_count Count of requests timed.")
            out.append("# TYPE http_request_duration_seconds_count counter")
            for (method, path), c in sorted(self.duration_count.items()):
                out.append(f'http_request_duration_seconds_count{{method="{self._esc(method)}",'
                           f'path="{self._esc(path)}"}} {c}')

            out.append("# HELP llm_tokens_total LLM tokens consumed.")
            out.append("# TYPE llm_tokens_total counter")
            for (kind, direction), n in sorted(self.llm_tokens.items()):
                out.append(f'llm_tokens_total{{kind="{self._esc(kind)}",'
                           f'direction="{self._esc(direction)}"}} {n}')

            if self.job_status:
                out.append("# HELP generation_jobs_by_status Current generation jobs by status.")
                out.append("# TYPE generation_jobs_by_status gauge")
                for status, n in sorted(self.job_status.items()):
                    out.append(f'generation_jobs_by_status{{status="{self._esc(status)}"}} {n}')
        return "\n".join(out) + "\n"


metrics = Metrics()


class JsonLogFormatter(logging.Formatter):
    """结构化一行 JSON：时间/级别/logger/消息/request_id（有则带）。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(json_logs: bool) -> None:
    """把根 logger 换成 JSON 行格式（仅当 json_logs=True）。"""
    if not json_logs:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


class Timer:
    def __enter__(self) -> "Timer":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc) -> None:
        self.elapsed = time.perf_counter() - self._t0
