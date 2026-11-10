"""迁移-模型一致性门（防 schema 漂移）。

背景：测试用 `create_all` 建表，alembic 迁移因此长期不被测试覆盖——迁移漏列/漏表
时生产 `alembic upgrade head` 会静默缺字段。本用例在空库上真跑迁移，再与
`Base.metadata` 逐表逐列比对，差异非空即失败。
"""
import os
import sqlite3
import subprocess
import sys
import tempfile

from app.models import Base


def _alembic_upgrade(db_path: str) -> None:
    env = dict(os.environ)
    env["SC_DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    assert proc.returncode == 0, f"alembic upgrade head 失败:\n{proc.stderr[-2000:]}"


def test_migrations_match_models():
    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "mig.sqlite")
        _alembic_upgrade(db_path)
        con = sqlite3.connect(db_path)
        migrated = {
            r[0]
            for r in con.execute(
                "select name from sqlite_master where type='table' and name!='alembic_version'"
            )
        }
        models = set(Base.metadata.tables)
        assert not (models - migrated), f"迁移缺表: {sorted(models - migrated)}"
        assert not (migrated - models), f"迁移多表（模型未声明）: {sorted(migrated - models)}"

        for table in sorted(models & migrated):
            db_cols = {r[1] for r in con.execute(f"PRAGMA table_info('{table}')")}
            model_cols = {c.name for c in Base.metadata.tables[table].columns}
            assert model_cols == db_cols, (
                f"表 {table} 列不一致: 模型多 {sorted(model_cols - db_cols)}，"
                f"迁移多 {sorted(db_cols - model_cols)}"
            )
