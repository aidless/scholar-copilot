"""格式排版端点：列出全部格式档案（参数透明，规则不黑箱）。"""
from fastapi import APIRouter

from ..export.formatter import FORMAT_PROFILES

router = APIRouter(prefix="/formatting", tags=["formatting"])


@router.get("/profiles")
async def list_profiles():
    return [{
        "key": key,
        "label": spec["label"],
        "body": spec["body"],
        "headings": {f"heading{level}": spec[f"heading{level}"] for level in (1, 2, 3)},
        "page": spec["page"],
    } for key, spec in FORMAT_PROFILES.items()]
