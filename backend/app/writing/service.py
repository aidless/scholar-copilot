"""写作服务层工具：字数统计 / 配额台账 / 章节字数分配。"""
import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import QuotaLedger

_PRICE_BASE = {"本科": 0.03, "硕士": 0.04, "博士": 0.05}


def price_cents(education: str, word_count: int) -> int:
    """透明计价公式：单价（元/字）× 字数 → 分。与 /billing/quote 同源。"""
    base = _PRICE_BASE.get(education)
    if base is None:
        raise ValueError(f"不支持的学历层次：{education}")
    return int(word_count * base * 100)


async def quota_used(db: AsyncSession, user_id: str, kind: str = "outline") -> int:
    """已用量 = Σ(消费/冲正行)，append-only。"""
    total = await db.scalar(
        select(func.coalesce(func.sum(QuotaLedger.delta), 0)).where(
            QuotaLedger.user_id == user_id, QuotaLedger.kind == kind,
            QuotaLedger.is_usage == True,  # noqa: E712——SQLAlchemy 列比较需显式 True
        )
    )
    return int(total or 0)


async def quota_granted(db: AsyncSession, user_id: str, kind: str = "outline") -> int:
    """管理员赠送/回收净额（非消费行）。"""
    total = await db.scalar(
        select(func.coalesce(func.sum(QuotaLedger.delta), 0)).where(
            QuotaLedger.user_id == user_id, QuotaLedger.kind == kind,
            QuotaLedger.is_usage == False,  # noqa: E712
        )
    )
    return int(total or 0)


async def quota_remaining(db: AsyncSession, user_id: str, kind: str = "outline") -> int:
    used = await quota_used(db, user_id, kind)
    granted = await quota_granted(db, user_id, kind)
    return max(settings.free_outline_limit - used + granted, 0)


def count_words(content_md: str) -> int:
    """中文字数近似：剥掉 Markdown 符号与空白后按字符计。"""
    text = re.sub(r"[#>*`|\-=_\[\]()!]+", "", content_md)
    return len(re.sub(r"\s", "", text))


def allocate_words(total: int, n_chapters: int) -> list[int]:
    """把目标字数按章均分，余数给靠前的章；每章保底 300 字。

    移植自 thesis_auto_generator ChapterGenerator._allocate_words 的简化版。
    """
    if n_chapters <= 0:
        return []
    floor = 300
    share = max(total // n_chapters, floor)
    alloc = [share] * n_chapters
    remainder = max(total - share * n_chapters, 0)
    for i in range(len(alloc)):
        add = min(remainder, 500)
        alloc[i] += add
        remainder -= add
        if remainder <= 0:
            break
    return alloc
