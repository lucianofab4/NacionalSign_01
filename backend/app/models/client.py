# Client model
from __future__ import annotations

from uuid import UUID

from sqlmodel import Field

from app.models.base import TimestampedModel, UUIDModel


class Client(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "clients"

    tenant_id: UUID = Field(foreign_key="tenants.id", index=True)
    name: str = Field(max_length=180)
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=32)
    portal_token: UUID | None = Field(default=None, index=True)
    portal_url: str | None = Field(default=None, max_length=512)
    notes: str | None = Field(default=None)
