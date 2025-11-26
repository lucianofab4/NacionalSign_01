from __future__ import annotations

from uuid import UUID

from sqlmodel import Field

from app.models.base import TimestampedModel, UUIDModel


class Contact(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "contacts"

    tenant_id: UUID = Field(foreign_key="tenants.id", index=True)
    full_name: str = Field(max_length=255)
    email: str | None = Field(default=None, max_length=255)
    cpf: str | None = Field(default=None, max_length=32)
    phone_number: str | None = Field(default=None, max_length=32)
    company_name: str | None = Field(default=None, max_length=128)
    company_tax_id: str | None = Field(default=None, max_length=32)
