"""导出 openapi.yaml（契约文件由代码生成，勿手改）。

用法（在 backend/ 下）：
    python -m scripts.export_openapi              # 写 ../openapi.yaml
    python -m scripts.export_openapi --out x.yaml # 写指定路径
    python -m scripts.export_openapi --check      # 只校验，不写（CI/本地预检用）

为什么要脚本而不是手写：手写契约与代码必然漂移（本项目从 18 个端点长到 53 个时
就是这么脱节的）。tests/test_openapi_sync.py 会挡住「改了端点没重新导出」。
"""
import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_OUT = BACKEND.parent / "openapi.yaml"

DESCRIPTION = """Scholar Copilot 后端契约（由 FastAPI 从代码导出，勿手改）。

鉴权：Bearer JWT（`Authorization: Bearer <token>`）。管理端与分销端各自独立 token。
资源隔离：所有用户资源查询强制 tenant+owner 过滤；属主不符统一 404（不泄露存在性）。
计费配额：价格与配额全部服务端判定；配额不足 402；未支付生成正文 402。
限流：登录 20/min、LLM 类 10/min、检索 30/min，超限 429 + `Retry-After`。
任务：生成类端点默认 202 返回 `{job_id,status}`，用 `GET /jobs/{id}` 轮询或
`WS /jobs/{id}/ws?token=` 订阅进度。
"""


def build_spec() -> dict:
    from app.main import VERSION, create_app

    spec = create_app().openapi()
    spec["info"] = {
        "title": "Scholar Copilot API",
        "version": VERSION,
        "description": DESCRIPTION,
    }
    spec["servers"] = [
        {"url": "http://localhost:8000", "description": "本地开发"},
    ]
    # 鉴权方案：路由用 Header 依赖而非 Security 依赖解析 Bearer，FastAPI 不会自动生成
    # securitySchemes。这里显式补上，否则 SDK 生成器不会带 Authorization 头。
    # 不设全局 security：/health、/auth/*、/references/search 等是匿名端点。
    # FastAPI 自动生成的 ValidationError 会带上游 pydantic 版本的字段
    # （实测 pydantic 2.14.2 只有 loc/msg/type，2.14.3 多了 ctx/input），
    # 直接导出会让契约文件随依赖小版本漂移、一致性门在 CI 上假红。
    # 这里固定成我们承诺的三字段形状——它本来就不是我们定义的契约内容。
    schemas = (spec.setdefault("components", {})).setdefault("schemas", {})
    if "ValidationError" in schemas:
        schemas["ValidationError"] = {
            "title": "ValidationError",
            "type": "object",
            "required": ["loc", "msg", "type"],
            "properties": {
                "loc": {"title": "Location", "type": "array",
                        "items": {"anyOf": [{"type": "string"}, {"type": "integer"}]}},
                "msg": {"title": "Message", "type": "string"},
                "type": {"title": "Error Type", "type": "string"},
            },
            "description": "单个字段的校验错误。上游 pydantic 可能附加 ctx/input 等字段，"
                           "契约只承诺 loc/msg/type 三项。",
        }

    components = spec.setdefault("components", {})
    components.setdefault("securitySchemes", {})["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "登录/注册返回的 access_token，按 `Authorization: Bearer <token>` 传递。"
                       "管理端与分销端 token 角色不同，不通用。",
    }
    # 需要鉴权的端点逐个标注（与代码里挂 current_user/admin_user/distributor_user 的一致）
    for path, ops in spec["paths"].items():
        if not _needs_auth(path):
            continue
        for op in ops.values():
            if isinstance(op, dict):
                op.setdefault("security", [{"BearerAuth": []}])
    return spec


_ANONYMOUS_PREFIXES = (
    "/health",
    "/auth/login",
    "/auth/register",
    "/auth/sms/send",
    "/auth/wechat/qrcode",
    "/auth/wechat/poll",
    "/auth/wechat/mock-approve",
    "/tenant/branding",
    "/billing/quote",
    "/formatting/profiles",
    "/references/search",
    "/references/verify",
    "/admin/login",
    "/distributor/login",
)


def _needs_auth(path: str) -> bool:
    return not any(path == p or path.startswith(p) for p in _ANONYMOUS_PREFIXES)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="导出 OpenAPI 契约")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出路径")
    ap.add_argument("--check", action="store_true", help="只校验文件是否最新，不写")
    args = ap.parse_args(argv)

    import yaml

    spec = build_spec()
    out = Path(args.out)

    if args.check:
        if not out.exists():
            print(f"缺少 {out}", file=sys.stderr)
            return 1
        current = yaml.safe_load(out.read_text(encoding="utf-8"))
        if json.dumps(current, sort_keys=True) != json.dumps(spec, sort_keys=True):
            print(f"{out} 与代码不一致，请重新导出", file=sys.stderr)
            return 1
        print(f"{out} 已是最新（{len(spec['paths'])} 个路径）")
        return 0

    out.write_text(
        yaml.safe_dump(spec, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )
    print(f"已写入 {out}（{len(spec['paths'])} 个路径，"
          f"{len((spec.get('components') or {}).get('schemas') or {})} 个 schema）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
