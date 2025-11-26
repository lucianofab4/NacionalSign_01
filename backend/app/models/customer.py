from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field

from app.models.base import TimestampedModel, UUIDModel


class Customer(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "customers"

    corporate_name: str = Field(index=True)
    trade_name: str | None = Field(default=None)
    cnpj: str = Field(unique=True, index=True, max_length=18)

    responsible_name: str
    responsible_email: str | None = Field(default=None)
    responsible_phone: str | None = Field(default=None, max_length=32)

    plan_id: UUID | None = Field(default=None, foreign_key="plans.id")
    document_quota: int | None = Field(default=None)
    documents_used: int = Field(default=0)

    tenant_id: UUID | None = Field(default=None, foreign_key="tenants.id")
    activation_token: str | None = Field(default=None, max_length=64, index=True)

    contract_storage_path: str | None = Field(default=None, max_length=512)
    contract_original_filename: str | None = Field(default=None, max_length=255)
    contract_mime_type: str | None = Field(default=None, max_length=128)
    contract_uploaded_at: datetime | None = Field(default=None)

    is_active: bool = Field(default=True)
