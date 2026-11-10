"""时区列一致性门（Postgres 专属故障的静态前置检查）。

背景（2026-11-10 实测）：模型用 `datetime.now(timezone.utc)` 生成 aware datetime，
但列类型是 `DateTime`（无 timezone）→ SQLite 静默接受，Postgres 报
`asyncpg ... can't subtract offset-naive and offset-aware datetimes`，
后端容器**启动即崩**（bootstrap superadmin 那一步）。测试全绿但 compose 起不来。

修法：所有时间列 `DateTime(timezone=True)`，迁移同步。本用例把「列必须带时区」
做成静态断言，不依赖数据库后端。
"""
from sqlalchemy import DateTime

from app.models import Base


def test_all_datetime_columns_are_timezone_aware():
    offenders = []
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            if isinstance(col.type, DateTime) and not col.type.timezone:
                offenders.append(f"{table.name}.{col.name}")
    assert not offenders, (
        "以下时间列缺 timezone=True（Postgres 下会因 aware/naive 混用崩溃）: "
        + ", ".join(offenders)
    )


def test_datetime_defaults_are_timezone_aware():
    """默认值函数产出的必须是 aware datetime（否则写库同样崩）。"""
    from app.models import _now

    value = _now()
    assert value.tzinfo is not None, "_now() 返回 naive datetime"
