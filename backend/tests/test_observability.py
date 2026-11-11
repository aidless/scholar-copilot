"""v1.8 #12：可观测性 —— Prometheus 文本指标 / 请求追踪 / 结构化日志。"""
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.observability import JsonLogFormatter, Metrics, metrics


@pytest.fixture(autouse=True)
def _clean_metrics():
    metrics.reset()
    yield
    metrics.reset()


def make_client():
    from app.main import create_app
    return TestClient(create_app())


def test_metrics_exposition_format_and_escaping():
    m = Metrics()
    m.observe_request("GET", "/x", 200, 0.5)
    m.observe_tokens("chapter", 10, 20)
    text = m.render()
    assert "# TYPE http_requests_total counter" in text
    assert 'http_requests_total{method="GET",path="/x",status="200"} 1' in text
    assert 'http_request_duration_seconds_sum{method="GET",path="/x"} 0.500000' in text
    assert 'llm_tokens_total{kind="chapter",direction="in"} 10' in text
    assert 'llm_tokens_total{kind="chapter",direction="out"} 20' in text
    # 标签注入防护
    m2 = Metrics()
    m2.observe_request('G"T', "/a\nb", 200, 0.1)
    assert 'method="G\\"T"' in m2.render().replace("\\\\", "\\")


def test_metrics_endpoint_exposes_and_counts():
    client = make_client()
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert "http_requests_total" in r.text
    # 打一次 /health 后应有该路径计数
    client.get("/health")
    r = client.get("/metrics")
    assert 'path="/health"' in r.text
    assert 'status="200"' in r.text


def test_metrics_uses_route_template_not_raw_path():
    client = make_client()
    # 打一个不存在的路径（404，无路由模板）→ __unmatched__，不产生高基数
    client.get("/no-such-endpoint-xyz")
    text = client.get("/metrics").text
    assert 'path="__unmatched__"' in text


def test_request_id_header_present_and_echoed():
    client = make_client()
    r = client.get("/health")
    assert r.headers.get("X-Request-Id")
    rid = "abc123fixed"
    r2 = client.get("/health", headers={"X-Request-Id": rid})
    assert r2.headers["X-Request-Id"] == rid


def test_json_log_formatter_emits_valid_json():
    fmt = JsonLogFormatter()
    record = logging.LogRecord(name="app.test", level=logging.WARNING, pathname="x",
                               lineno=1, msg="出错了 %s", args=("原因",), exc_info=None)
    line = fmt.format(record)
    obj = json.loads(line)  # 必须是合法 JSON
    assert obj["level"] == "WARNING"
    assert obj["msg"] == "出错了 原因"
    assert "request_id" in obj


def test_configure_logging_json_toggle():
    from app.observability import configure_logging
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        configure_logging(False)  # 不改
        assert root.handlers == before
        configure_logging(True)
        assert any(isinstance(h.formatter, JsonLogFormatter) for h in root.handlers)
    finally:
        root.handlers = before
