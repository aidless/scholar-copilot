"""对象存储抽象：默认本地磁盘（clone 即跑），可选 S3/MinIO。

为什么默认本地：用户 `cp .env.example .env && docker compose up` 时不该被强绑一个
对象存储服务。S3/MinIO 通过 SC_STORAGE_BACKEND=s3 + boto3 启用（boto3 为可选依赖，
未安装时用 s3 会给出明确报错而非 ImportError 堆栈）。

存储键（key）约定：`{tenant_id}/{uuid}{ext}`，与业务 id 解耦，便于按租户归档/清理。
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from .config import settings


class StorageError(RuntimeError):
    pass


class LocalStorage:
    backend = "local"

    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        # 防目录穿越：解析后必须仍在 root 内
        if not str(p).startswith(str(self.root.resolve())):
            raise StorageError("非法存储键（越界）")
        return p

    def save(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            pass

    def url(self, key: str, expires: int = 3600) -> str:
        # 本地后端不签 URL，返回应用内下载路径（由路由做鉴权）
        return f"/files/download?key={key}"


class S3Storage:
    backend = "s3"

    def __init__(self) -> None:
        try:
            import boto3  # 可选依赖
        except ImportError as exc:  # pragma: no cover - 环境相关
            raise StorageError(
                "使用 S3 存储需先安装 boto3（pip install boto3）") from exc
        self.bucket = settings.s3_bucket
        if not self.bucket:
            raise StorageError("SC_STORAGE_BACKEND=s3 但未配置 SC_S3_BUCKET")
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint or None,
            aws_access_key_id=settings.s3_access_key or None,
            aws_secret_access_key=settings.s3_secret_key or None,
            region_name=settings.s3_region or None,
        )

    def save(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def read(self, key: str) -> bytes:
        obj = self.client.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def url(self, key: str, expires: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires)


_STORAGE = None


def get_storage():
    """惰性单例：按配置返回本地或 S3 后端。"""
    global _STORAGE
    if _STORAGE is None:
        if settings.storage_backend == "s3":
            _STORAGE = S3Storage()
        else:
            _STORAGE = LocalStorage(settings.storage_dir)
    return _STORAGE


def reset_storage() -> None:
    """测试用：清掉单例（切换配置后需要）。"""
    global _STORAGE
    _STORAGE = None


def make_key(tenant_id: str, ext: str) -> str:
    ext = ext if ext.startswith(".") else f".{ext}"
    return f"{tenant_id}/{uuid.uuid4().hex}{ext}"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
