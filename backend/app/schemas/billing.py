from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import IDModel, Timestamped


class PlanRead(IDModel, Timestamped):
    name: str
    document_quota: int
    user_quota: int
    price_monthly: int
    price_yearly: int
    is_active: bool


class SubscriptionRead(IDModel, Timestamped):
    tenant_id: UUID
    plan_id: UUID
    status: str
    valid_until: datetime | None
    auto_renew: bool


class SubscriptionCreate(BaseModel):
    plan_id: UUID
    payment_method_token: str


class InvoiceRead(IDModel, Timestamped):
    tenant_id: UUID
    gateway: str
    external_id: str
    amount_cents: int
    due_date: datetime
    status: str
    paid_at: datetime | None
    # Retry/dunning fields
    retry_count: int | None = None
    last_attempt_at: datetime | None = None
    next_attempt_at: datetime | None = None
    # Tax/receipt placeholders
    tax_id: str | None = None
    receipt_url: str | None = None
    fiscal_note_number: str | None = None


class UsageRead(BaseModel):
    tenant_id: UUID
    period_start: datetime
    period_end: datetime
    documents_used: int
    documents_quota: int | None
    users_used: int
    users_quota: int | None
    # Campos adicionais para facilitar UI
    documents_percent: float | None = None
    users_percent: float | None = None
    near_limit: bool = False
    message: str | None = None


class WalletRead(BaseModel):
    balance_cents: int


class WalletCredit(BaseModel):
    amount_cents: int
