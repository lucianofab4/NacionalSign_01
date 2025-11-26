from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import boto3
from botocore.client import Config as BotoConfig

from app.core.config import settings


def resolve_storage_root() -> Path:
    env_dir = os.getenv("NACIONALSIGN_STORAGE")
    base = Path(env_dir) if env_dir else Path("storage")
    try:
        return base.resolve()
    except Exception:
        return base


def normalize_storage_path(value: str) -> str:
    path = Path(value)
    base = resolve_storage_root()
    try:
        return str(path.resolve().relative_to(base))
    except Exception:
        return str(path)


class StorageBackend(Protocol):
    def save_bytes(self, *, root: str, name: str, data: bytes) -> str:  # returns storage path/URL
        ...

    def presigned_url(self, *, path: str, expires_seconds: int = 3600) -> str | None:
        ...

    def load_bytes(self, path: str) -> bytes:
        ...


@dataclass
class LocalStorage:
    base_dir: Path

    def save_bytes(self, *, root: str, name: str, data: bytes) -> str:
        target_dir = self.base_dir / root
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / name
        file_path.write_bytes(data)
        return str(file_path)

    def presigned_url(self, *, path: str, expires_seconds: int = 3600) -> str | None:  # noqa: ARG002
        # Not applicable for local storage; could return file:// URL
        return None

    def load_bytes(self, path: str) -> bytes:
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = self.base_dir / path
        return file_path.read_bytes()


@dataclass
class S3Storage:
    bucket: str
    client: any

    def save_bytes(self, *, root: str, name: str, data: bytes) -> str:
        key = f"{root.strip('/')}/{name}"
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
        return f"s3://{self.bucket}/{key}"

    def presigned_url(self, *, path: str, expires_seconds: int = 3600) -> str | None:
        if not path.startswith("s3://"):
            return None
        _, rest = path.split("s3://", 1)
        bucket, key = rest.split("/", 1)
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )

    def load_bytes(self, path: str) -> bytes:
        if not path.startswith("s3://"):
            raise ValueError("Expected s3:// path for S3 storage")
        _, rest = path.split("s3://", 1)
        bucket, key = rest.split("/", 1)
        response = self.client.get_object(Bucket=bucket, Key=key)
        body = response.get("Body")
        return body.read() if body else b""


def get_storage() -> StorageBackend:
    # During tests, prefer local storage to avoid external dependencies unless explicitly allowed
    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("NACIONALSIGN_ALLOW_S3_IN_TESTS") != "1":
        from app.services.document import BASE_STORAGE  # local import to avoid cycle at module import

        return LocalStorage(base_dir=BASE_STORAGE)

    # If explicit local storage path is provided, honor it
    if os.getenv("NACIONALSIGN_STORAGE"):
        from app.services.document import BASE_STORAGE  # local import to avoid cycle at module import

        return LocalStorage(base_dir=BASE_STORAGE)

    # In debug with SQLite (typical local/dev and tests), default to local storage unless explicitly overridden
    try:
        if getattr(settings, "debug", False) and str(getattr(settings, "database_url", "")).startswith("sqlite"):
            from app.services.document import BASE_STORAGE  # local import to avoid cycle at module import

            return LocalStorage(base_dir=BASE_STORAGE)
    except Exception:
        # If settings is not fully initialized, ignore and continue
        pass

    # Prefer S3 when endpoint and credentials are available
    if settings.s3_endpoint_url and settings.s3_access_key and settings.s3_secret_key and settings.s3_bucket_documents:
        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=BotoConfig(signature_version="s3v4"),
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
        return S3Storage(bucket=settings.s3_bucket_documents, client=client)

    # Fallback to local storage under BASE_STORAGE
    from app.services.document import BASE_STORAGE  # local import to avoid cycle at module import

    return LocalStorage(base_dir=BASE_STORAGE)
