"""#19 内容指纹链：让「AI 参与度 A/B/C」可审计。

问题：A/B/C 标记是系统自己给自己开的证明。原始设计只靠一个 `ai_level` 字段，
用户/审计者无法验证「这稿确实被人改过」。

做法：建立 append-only 的**指纹链**——
- 每次生成/改写都记一条：内容 sha256 + 当时声明的 ai_level + 与上一版的相似度；
- 指纹对空白不敏感（换行/空格不算「改」），对内容敏感；
- 「A → B」这个升级动作本身在链上留痕：`kind=edit` 且 similarity<1.0，
  即「AI 初稿被人改过」的客观证据。

链只追加，不改写——与 quota_ledger / admin_audit_log 同一纪律。
"""
from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import GenerationProvenance


def _normalize(text: str) -> str:
    return re.sub(r"\s", "", text or "")


def fingerprint(text: str) -> str:
    """内容指纹（sha256，对空白不敏感）。"""
    return hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()


def diff_ratio(a: str, b: str) -> float:
    """两段文本的相似度（0~1）。空文本视为完全相同。"""
    na, nb = _normalize(a), _normalize(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb, autojunk=False).ratio()


async def record_event(db: AsyncSession, *, tenant_id: str, order_id: str, node_id: str,
                       kind: str, content: str, ai_level: str,
                       prev_content: str | None = None,
                       job_id: str | None = None, actor: str | None = None,
                       ) -> GenerationProvenance:
    """往指纹链追加一条。

    `prev_content`：调用方若还留着上一版原文（生成/改写流程里都拿得到），传进来，
    链上就能算出「这版与上一版有多像」——这是 A→B 升级的客观依据。
    """
    row = GenerationProvenance(
        tenant_id=tenant_id,
        order_id=order_id,
        node_id=node_id,
        kind=kind,
        content_sha256=fingerprint(content),
        word_count=len(_normalize(content)),
        ai_level=ai_level,
        job_id=job_id,
        actor=actor,
    )
    if prev_content is not None:
        row.sim_to_prev = round(diff_ratio(prev_content, content), 4)
    else:
        row.sim_to_prev = None
    db.add(row)
    await db.flush()
    return row


async def chain_for_order(db: AsyncSession, order_id: str) -> list[dict]:
    """取某订单的完整指纹链（按时间升序）。"""
    rows = (await db.execute(
        select(GenerationProvenance)
        .where(GenerationProvenance.order_id == order_id)
        .order_by(GenerationProvenance.created_at, GenerationProvenance.id)
    )).scalars().all()
    return [{
        "id": r.id,
        "node_id": r.node_id,
        "kind": r.kind,
        "content_sha256": r.content_sha256,
        "word_count": r.word_count,
        "ai_level": r.ai_level,
        "similarity": r.sim_to_prev,
        "job_id": r.job_id,
        "actor": r.actor,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]
