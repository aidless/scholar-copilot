"""格式排版端点：列出全部格式档案（内置通用/校样例 + 租户自建），参数透明。

v1.12 #10 起格式规则从「代码里写死 4 条」升级成「数据」：管理端可建模板，
导出的 profile 参数按 key 解析，内置与自建共用同一解析器（不黑箱）。
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import FormatTemplate
from ..export.templates import builtin_profiles

router = APIRouter(prefix="/formatting", tags=["formatting"])


def _shape(key: str, spec: dict, *, builtin: bool, tpl_id: str | None = None,
           school: str | None = None, degree: str | None = None) -> dict:
    return {
        "id": tpl_id,
        "key": key,
        "label": spec["label"],
        "school": school if school is not None else spec.get("school", ""),
        "degree": degree if degree is not None else spec.get("degree", ""),
        "note": spec.get("note"),
        "builtin": builtin,
        "body": spec["body"],
        "headings": {f"heading{level}": spec[f"heading{level}"] for level in (1, 2, 3)},
        "page": spec["page"],
    }


@router.get("/profiles")
async def list_profiles(db: AsyncSession = Depends(get_db)):
    """全部可用格式档案：内置（通用 + 校样例）+ 全部租户自建模板。"""
    out = [_shape(key, spec, builtin=True)
           for key, spec in builtin_profiles().items()]
    rows = (await db.execute(
        select(FormatTemplate).order_by(FormatTemplate.created_at)
    )).scalars().all()
    for row in rows:
        try:
            out.append(_shape(row.key, row.spec_json, builtin=False, tpl_id=row.id,
                              school=row.school, degree=row.degree))
        except KeyError:  # 历史脏数据不至于打挂整个列表
            continue
    return out


async def resolve_profile(db: AsyncSession, key: str) -> dict | None:
    """按 key 解析格式档案：先内置，再租户自建。返回 None 表示不存在。"""
    builtin = builtin_profiles()
    if key in builtin:
        return builtin[key]
    row = (await db.execute(
        select(FormatTemplate).where(FormatTemplate.key == key)
        .order_by(FormatTemplate.created_at).limit(1)
    )).scalar()
    return row.spec_json if row is not None else None
