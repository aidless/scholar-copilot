"""openapi.yaml 与代码一致性门。

为什么需要：`openapi.yaml` 原来是手写的骨架（18 个端点，带 `x-origin` 对照），
代码早就长到 53 个端点，文档与实现静默脱节——外部按契约对接时会踩空。
现在改为从 FastAPI 导出，并加这道门：**代码改了端点却没重新导出，测试就红**。

重新生成：
    python -m scripts.export_openapi        # 在 backend/ 下执行
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SPEC = BACKEND.parent / "openapi.yaml"


def _code_paths() -> set[str]:
    from app.main import create_app

    return set(create_app().openapi()["paths"].keys())


def test_openapi_yaml_exists():
    assert SPEC.exists(), f"缺少 {SPEC}（跑 python -m scripts.export_openapi 生成）"


def test_openapi_yaml_matches_code():
    """契约文件里的路径集合必须与代码一致（多一个少一个都算漂移）。"""
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    in_file = set(doc["paths"].keys())
    in_code = _code_paths()

    missing = sorted(in_code - in_file)   # 代码有、文档没有
    stale = sorted(in_file - in_code)     # 文档有、代码没有
    assert not missing, f"openapi.yaml 缺这些端点（跑 export_openapi 重生成）：{missing}"
    assert not stale, f"openapi.yaml 有已不存在的端点（跑 export_openapi 重生成）：{stale}"


def test_openapi_yaml_version_matches_app():
    """契约版本号必须跟 app 版本一致，否则外部无法判断对接的是哪一版。"""
    yaml = pytest.importorskip("yaml")
    from app.main import VERSION

    doc = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    assert doc["info"]["version"] == VERSION, (
        f"openapi.yaml 版本 {doc['info']['version']} != app VERSION {VERSION}"
    )


def test_openapi_yaml_has_security_scheme():
    """鉴权方案必须写在契约里（否则 SDK 生成器不会带 Authorization 头）。"""
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    schemes = (doc.get("components") or {}).get("securitySchemes") or {}
    assert any(v.get("scheme") == "bearer" for v in schemes.values()), schemes


def test_export_script_regenerates_same_content(tmp_path):
    """导出脚本必须可复现：重跑一次，内容与仓库里的文件逐字节相同。

    这条比「路径集合相同」更严——它能抓出描述文字/字段定义被改动却没提交的情况。
    """
    yaml = pytest.importorskip("yaml")
    env = dict(os.environ)
    env.update({
        "SC_DATABASE_URL": "sqlite+aiosqlite:///" + str(tmp_path / "x.db"),
        "SC_JWT_SECRET": "test-secret",
        "SC_DB_AUTO_CREATE": "true",
    })
    out = tmp_path / "openapi.yaml"
    r = subprocess.run(
        [sys.executable, "-m", "scripts.export_openapi", "--out", str(out)],
        cwd=BACKEND, env=env, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr[-2000:]

    fresh = yaml.safe_load(out.read_text(encoding="utf-8"))
    current = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    assert json.dumps(fresh, sort_keys=True) == json.dumps(current, sort_keys=True), (
        "openapi.yaml 与代码导出的结果不一致（跑 python -m scripts.export_openapi 更新）"
    )
