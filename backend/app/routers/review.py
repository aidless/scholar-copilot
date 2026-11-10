"""核查面板：移植 review-workflow / tmaudit 的规则（引用、数字、统计口径）。"""
from fastapi import APIRouter, Depends, HTTPException

from ..db import get_db

router = APIRouter(prefix="/review", tags=["review"])


@router.post("/orders/{order_id}/audit")
async def audit(order_id: str, db=Depends(get_db)):
    # TODO(v0.4): 引用核查 + 数字一致性 + AI 参与度标记复核，产出报告
    raise HTTPException(501, "v0.4 实现：移植 review-workflow 规则")
