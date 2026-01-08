from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr

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
    documents_signed: int | None = None
    users_used: int
    users_quota: int | None
    # Campos adicionais para facilitar UI
    documents_percent: float | None = None
    documents_signed_percent: float | None = None
    users_percent: float | None = None
    near_limit: bool = False
    message: str | None = None


class WalletRead(BaseModel):
    balance_cents: int


class WalletCredit(BaseModel):
    amount_cents: int


class TenantUsageAdminRow(UsageRead):
    tenant_name: str
    tenant_slug: str
    plan_id: UUID | None = None
    plan_name: str | None = None
    subscription_status: str | None = None
    limit_state: str
    limit_ratio: float | None = None


class AdminUsageResponse(BaseModel):
    total: int
    period_start: datetime
    period_end: datetime
    items: list[TenantUsageAdminRow]
    alerts: list[TenantUsageAdminRow]


class UsageAlertRequest(BaseModel):
    start_date: datetime | None = None
    end_date: datetime | None = None
    emails: list[EmailStr] | None = None
    threshold: float | None = None
    only_exceeded: bool = False
