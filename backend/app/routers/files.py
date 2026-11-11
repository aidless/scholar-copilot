"""文件上传/下载端点（v1.9）：对象存储 + 元数据表 + 白名单 + 大小上限。

安全要点：
- 扩展名白名单（拒绝 .exe/.sh/.php 等可执行/脚本）；大小上限 SC_MAX_UPLOAD_MB；
- 内容按 sha256 记录（可用于同一文件去重/溯源）；
- 所有读写先过 ownership_filter（IDOR：非本人一律 404）；
- 存储键 `{tenant}/{uuid}{ext}`，LocalStorage 另做目录穿越防护。
"""
from __future__ import annotations

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Query,
                     Response, UploadFile)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import UploadedFile
from ..storage import get_storage, make_key, sha256_hex
from ..tenancy import CurrentUser, current_user, ownership_filter

router = APIRouter(prefix="/files", tags=["files"])

# 允许的扩展名 → 归类说明（仅白名单，未知一律拒绝）
ALLOWED_EXT = {
    ".docx", ".doc", ".pdf", ".txt", ".md", ".rtf",
    ".pptx", ".xlsx", ".csv", ".jpg", ".jpeg", ".png",
}


def _ext_of(filename: str) -> str:
    name = (filename or "").lower()
    for ext in ALLOWED_EXT:
        if name.endswith(ext):
            return ext
    return ""


def _file_out(f: UploadedFile) -> dict:
    return {
        "id": f.id,
        "order_id": f.order_id,
        "kind": f.kind,
        "filename": f.filename,
        "content_type": f.content_type,
        "size": f.size,
        "sha256": f.sha256,
        "created_at": f.created_at.isoformat() if f.created_at else None,
        "download_url": f"/files/{f.id}/download",
    }


async def _get_owned_file(db: AsyncSession, user: CurrentUser, file_id: str) -> UploadedFile:
    query = ownership_filter(select(UploadedFile), UploadedFile, user).where(
        UploadedFile.id == file_id)
    row = (await db.execute(query)).scalar()
    if row is None:  # 统一 404
        raise HTTPException(404, "文件不存在")
    return row


@router.post("", status_code=201)
async def upload_file(upload: UploadFile = File(...),
                      kind: str = Form(default="attachment"),
                      order_id: str | None = Form(default=None),
                      db: AsyncSession = Depends(get_db),
                      user: CurrentUser = Depends(current_user)):
    ext = _ext_of(upload.filename)
    if not ext:
        raise HTTPException(422, f"不支持的文件类型；允许：{' '.join(sorted(ALLOWED_EXT))}")
    data = await upload.read()
    limit = settings.max_upload_mb * 1024 * 1024
    if len(data) > limit:
        raise HTTPException(413, f"文件超过 {settings.max_upload_mb}MB 上限")
    if not data:
        raise HTTPException(422, "空文件")
    key = make_key(user.tenant_id, ext)
    get_storage().save(key, data)
    row = UploadedFile(
        tenant_id=user.tenant_id, owner_id=user.user_id, order_id=order_id,
        kind=kind, filename=upload.filename, content_type=upload.content_type or "",
        size=len(data), storage_key=key, sha256=sha256_hex(data),
    )
    db.add(row)
    await db.commit()
    return _file_out(row)


@router.get("")
async def list_files(order_id: str | None = Query(default=None),
                     kind: str | None = Query(default=None),
                     db: AsyncSession = Depends(get_db),
                     user: CurrentUser = Depends(current_user)):
    query = ownership_filter(select(UploadedFile), UploadedFile, user)
    if order_id:
        query = query.where(UploadedFile.order_id == order_id)
    if kind:
        query = query.where(UploadedFile.kind == kind)
    rows = (await db.execute(query.order_by(UploadedFile.created_at.desc()))).scalars().all()
    return [_file_out(f) for f in rows]


@router.get("/{file_id}")
async def get_file(file_id: str, db: AsyncSession = Depends(get_db),
                   user: CurrentUser = Depends(current_user)):
    return _file_out(await _get_owned_file(db, user, file_id))


@router.get("/{file_id}/download")
async def download_file(file_id: str, db: AsyncSession = Depends(get_db),
                        user: CurrentUser = Depends(current_user)):
    row = await _get_owned_file(db, user, file_id)
    data = get_storage().read(row.storage_key)
    from urllib.parse import quote as _q
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{_q(row.filename)}"}
    return Response(content=data, media_type=row.content_type or "application/octet-stream",
                    headers=headers)


@router.get("/{file_id}/signed-url")
async def signed_url(file_id: str, db: AsyncSession = Depends(get_db),
                     user: CurrentUser = Depends(current_user)):
    """S3 后端返回临时预签名 URL；本地后端返回应用内下载路径。"""
    row = await _get_owned_file(db, user, file_id)
    return {"url": get_storage().url(row.storage_key), "expires_in": 3600}


@router.delete("/{file_id}", status_code=204)
async def delete_file(file_id: str, db: AsyncSession = Depends(get_db),
                      user: CurrentUser = Depends(current_user)):
    row = await _get_owned_file(db, user, file_id)
    get_storage().delete(row.storage_key)
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)
