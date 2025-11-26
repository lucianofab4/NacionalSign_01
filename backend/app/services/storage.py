from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import boto3
from botocore.client import Config as BotoConfig

from app.core.config import settings


def _determine_base_storage() -> Path:
    raw = (
        getattr(settings, "storage_base_path", None)
        or os.getenv("NACIONALSIGN_STORAGE")
        or getattr(settings, "nacionalsign_storage", None)
        or "storage"
    )
    try:
        return Path(raw).expanduser().resolve()
    except Exception:
        return Path(raw)


BASE_STORAGE = _determine_base_storage()


def _effective_base_storage() -> Path:
    env_override = os.getenv("NACIONALSIGN_STORAGE")
    if env_override:
        return BASE_STORAGE

    document_module = sys.modules.get("app.services.document")
    override = getattr(document_module, "BASE_STORAGE", None) if document_module else None
    if override:
        try:
            return Path(override)
        except Exception:
            return Path(str(override))
    return _effective_base_storage()


def resolve_storage_root() -> Path:
    """
    Retorna o diretório raiz onde todos os arquivos são armazenados.
    """
    return BASE_STORAGE


def normalize_storage_path(value: str | Path) -> str:
    """
    Garante que o caminho salvo seja relativo ao diretório base configurado.
    """
    path = Path(value)
    base = _effective_base_storage()
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

    def __post_init__(self) -> None:
        try:
            self.base_dir = self.base_dir.resolve()
        except Exception:
            self.base_dir = Path(self.base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

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

        candidates: list[Path] = []
        if file_path.is_absolute():
            candidates.append(file_path)
        else:
            candidates.append(self.base_dir / path)
            legacy_root = self.base_dir.parent / "storage"
            if legacy_root != self.base_dir:
                candidates.append(legacy_root / path)
            candidates.append(Path.cwd() / path)

        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                resolved = candidate
            if resolved.exists():
                return resolved.read_bytes()

        raise FileNotFoundError(f"Arquivo {path!r} nao foi encontrado no armazenamento configurado.")


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
        return LocalStorage(base_dir=_effective_base_storage())

    # If explicit local storage path is provided, honor it
    if os.getenv("NACIONALSIGN_STORAGE"):
        return LocalStorage(base_dir=_effective_base_storage())

    # In debug with SQLite (typical local/dev and tests), default to local storage unless explicitly overridden
    try:
        if getattr(settings, "debug", False) and str(getattr(settings, "database_url", "")).startswith("sqlite"):
            return LocalStorage(base_dir=_effective_base_storage())
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
    return LocalStorage(base_dir=_effective_base_storage())
