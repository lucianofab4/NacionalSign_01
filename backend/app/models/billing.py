from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field

from app.models.base import TimestampedModel, UUIDModel


class Plan(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "plans"

    name: str
    document_quota: int
    user_quota: int
    price_monthly: int
    price_yearly: int
    is_active: bool = Field(default=True)


class Subscription(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "subscriptions"

    tenant_id: UUID = Field(foreign_key="tenants.id", index=True)
    plan_id: UUID = Field(foreign_key="plans.id")
    status: str = Field(default="active")
    valid_until: datetime | None = Field(default=None)
    auto_renew: bool = Field(default=True)


class Invoice(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "invoices"

    tenant_id: UUID = Field(foreign_key="tenants.id", index=True)
    gateway: str
    external_id: str
    amount_cents: int
    due_date: datetime
    status: str
    paid_at: datetime | None = Field(default=None)
    # Payments hardening
    retry_count: int = Field(default=0)
    last_attempt_at: datetime | None = Field(default=None)
    next_attempt_at: datetime | None = Field(default=None)
    # Tax/receipt placeholders (MVP)
    tax_id: str | None = Field(default=None)
    receipt_url: str | None = Field(default=None)
    fiscal_note_number: str | None = Field(default=None)
