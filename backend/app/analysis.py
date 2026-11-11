"""数据分析 / 问卷统计（v1.9 #9）：描述统计 + 相关分析 + 频数分布。

输入一份表格（columns + rows），自动把「整列都能解析成数字」的列当数值列做
describe + 两两 Pearson 相关；其余列（或显式 categorical 指定）做频数分布。
纯 Python 实现（不引入 pandas/numpy 之外的依赖），零 IO。
"""
from __future__ import annotations

import math
from typing import Any


def _to_float(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def describe(values: list[float]) -> dict:
    """一列数值的描述统计（样本标准差，ddof=1）。"""
    xs = [v for v in values if v is not None]
    n = len(xs)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "std": None,
                "min": None, "max": None, "q1": None, "q3": None}
    ordered = sorted(xs)
    mean = sum(xs) / n
    if n % 2 == 1:
        median = ordered[n // 2]
    else:
        median = (ordered[n // 2 - 1] + ordered[n // 2]) / 2
    if n > 1:
        var = sum((x - mean) ** 2 for x in xs) / (n - 1)
        std = math.sqrt(var)
    else:
        std = 0.0

    def _quantile(p: float) -> float:
        # 线性插值分位数
        if n == 1:
            return ordered[0]
        pos = (n - 1) * p
        lo = math.floor(pos)
        hi = math.ceil(pos)
        if lo == hi:
            return ordered[lo]
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)

    return {
        "n": n, "mean": round(mean, 6), "median": round(median, 6),
        "std": round(std, 6), "min": min(xs), "max": max(xs),
        "q1": round(_quantile(0.25), 6), "q3": round(_quantile(0.75), 6),
    }


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson 相关系数；样本不足或某列方差为 0 时返回 None。"""
    n = len(xs)
    if n < 2 or len(ys) != n:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return round(cov / math.sqrt(vx * vy), 6)


def frequency(values: list[Any]) -> list[dict]:
    """频数分布（降序），带占比。"""
    total = len(values)
    counts: dict[str, int] = {}
    for v in values:
        key = "" if v is None else str(v)
        counts[key] = counts.get(key, 0) + 1
    rows = [{"value": k, "count": c, "pct": round(c / total * 100, 2) if total else 0.0}
            for k, c in counts.items()]
    rows.sort(key=lambda r: (-r["count"], r["value"]))
    return rows


def analyze(columns: list[str], rows: list[list[Any]], categorical: list[str] | None = None) -> dict:
    """对表格做统计分析。

    columns: 列名；rows: 每行的值列表（长度需与 columns 一致）；
    categorical: 强制按类别处理的列名（即使能解析成数字）。
    """
    categorical = set(categorical or [])
    if len(columns) == 0:
        raise ValueError("需要至少一列")
    for r in rows:
        if len(r) != len(columns):
            raise ValueError("每行长度必须与列数一致")

    numeric_cols: list[str] = []
    cat_cols: list[str] = []
    col_data: dict[str, list[Any]] = {c: [] for c in columns}
    for ci, col in enumerate(columns):
        col_data[col] = [r[ci] for r in rows]
        if col in categorical:
            cat_cols.append(col)
            continue
        parsed = [_to_float(v) for v in col_data[col]]
        non_null = [p for p in parsed if p is not None]
        # 至少一半非空且全部非空值可解析 → 数值列
        if non_null and len(non_null) >= max(1, len(rows) * 0.5):
            numeric_cols.append(col)
        else:
            cat_cols.append(col)

    numeric_stats = {}
    parsed_numeric: dict[str, list[float]] = {}
    for col in numeric_cols:
        vals = [_to_float(v) for v in col_data[col]]
        parsed_numeric[col] = [v for v in vals if v is not None]
        numeric_stats[col] = describe(vals)

    correlations = []
    for i in range(len(numeric_cols)):
        for j in range(i + 1, len(numeric_cols)):
            a, b = numeric_cols[i], numeric_cols[j]
            # 只对「同位置都非空」的配对求相关
            xs, ys = [], []
            for av, bv in zip(col_data[a], col_data[b]):
                fa, fb = _to_float(av), _to_float(bv)
                if fa is not None and fb is not None:
                    xs.append(fa)
                    ys.append(fb)
            r = pearson(xs, ys)
            if r is not None:
                correlations.append({"x": a, "y": b, "r": r})

    categorical_stats = {col: frequency(col_data[col]) for col in cat_cols}
    return {
        "n_rows": len(rows),
        "numeric": numeric_stats,
        "correlations": correlations,
        "categorical": categorical_stats,
    }
