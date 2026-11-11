"""v1.9 #9：数据分析 / 问卷统计（纯计算）。"""
import pytest
from fastapi.testclient import TestClient


def test_describe():
    from app.analysis import describe
    d = describe([1, 2, 3, 4])
    assert d["n"] == 4
    assert d["mean"] == 2.5
    assert d["median"] == 2.5
    assert abs(d["std"] - 1.290994) < 1e-6  # 样本标准差 ddof=1
    assert d["min"] == 1 and d["max"] == 4
    assert describe([])["n"] == 0


def test_pearson():
    from app.analysis import pearson
    assert pearson([1, 2, 3], [2, 4, 6]) == 1.0
    assert pearson([1, 2, 3], [6, 4, 2]) == -1.0
    assert pearson([1, 1, 1], [1, 2, 3]) is None  # 方差为 0
    assert pearson([1], [1]) is None  # 样本不足


def test_frequency():
    from app.analysis import frequency
    rows = frequency(["a", "b", "a", "a"])
    assert rows[0]["value"] == "a" and rows[0]["count"] == 3
    assert rows[0]["pct"] == 75.0
    assert rows[1]["value"] == "b" and rows[1]["count"] == 1


def test_analyze_mixed():
    from app.analysis import analyze
    res = analyze(
        columns=["分数", "时长", "性别"],
        rows=[[90, 10, "男"], [80, 20, "女"], [70, 30, "男"]],
    )
    assert res["n_rows"] == 3
    assert "分数" in res["numeric"] and res["numeric"]["分数"]["mean"] == 80
    assert "性别" in res["categorical"]
    assert res["categorical"]["性别"][0]["count"] == 2  # 男 ×2
    # 分数与时长完全负相关
    corr = {f'{c["x"]}-{c["y"]}': c["r"] for c in res["correlations"]}
    assert corr.get("分数-时长") == -1.0


def test_analyze_categorical_override():
    from app.analysis import analyze
    res = analyze(columns=["等级"], rows=[[1], [2], [1]], categorical=["等级"])
    assert "等级" in res["categorical"] and res["categorical"]["等级"][0]["count"] == 2


def test_analyze_rejects_bad_rows():
    from app.analysis import analyze
    with pytest.raises(ValueError):
        analyze(columns=["a", "b"], rows=[[1]])  # 行长度不符


def test_stats_endpoint():
    from app.main import create_app
    client = TestClient(create_app())
    body = {"columns": ["x", "y", "组"], "rows": [[1, 2, "A"], [2, 4, "B"], [3, 6, "A"]]}
    r = client.post("/tools/stats", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["n_rows"] == 3
    assert data["numeric"]["x"]["mean"] == 2
    assert data["correlations"][0]["r"] == 1.0
    # 行长度不符 → 422
    r = client.post("/tools/stats", json={"columns": ["a", "b"], "rows": [[1]]})
    assert r.status_code == 422
