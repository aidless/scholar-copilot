"""#8 API 层：自查与 AIGC 特征端点（先 RED 后 GREEN）。"""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app())


def test_selfcheck_endpoint_returns_evidence():
    resp = client.post("/tools/selfcheck", json={
        "text": "本文提出一种基于多模态特征融合的学术文本合规检测方法。",
        "references": [{
            "id": "R1",
            "title": "多模态特征融合",
            "text": "本文提出一种基于多模态特征融合的学术文本合规检测方法，并在数据集上验证。",
        }],
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["references"][0]["fragments"]
    assert data["verdict"] in {"high_overlap", "moderate_overlap", "low_overlap"}
    assert data["disclaimer"]


def test_selfcheck_rejects_empty_references():
    resp = client.post("/tools/selfcheck", json={"text": "一段文本", "references": []})
    assert resp.status_code == 422


def test_selfcheck_rejects_short_text():
    resp = client.post("/tools/selfcheck", json={"text": "短", "references": []})
    assert resp.status_code == 422


def test_aigc_features_endpoint():
    resp = client.post("/tools/aigc-features", json={
        "text": "随着经济的快速发展，该技术得到了广泛应用。众所周知，本文将给出分析。",
    })
    assert resp.status_code == 200, resp.text
    feats = resp.json()["features"]
    names = {f["feature"] for f in feats}
    assert "cliche_density" in names
    assert any(f["evidence"] for f in feats)


def test_detect_now_includes_aigc_features():
    resp = client.post("/tools/detect", json={"text": "随着经济的快速发展，本文将给出分析。综上所述，方法有效。"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "aigc_features" in data
    assert data["aigc_features"], "detect 应附带 AIGC 特征"
