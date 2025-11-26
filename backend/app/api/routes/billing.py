from __future__ import annotations

from typing import List
from uuid import UUID

import hmac
import hashlib
import time
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session

from app.api.deps import get_current_active_user, get_db, require_roles
from app.models.user import User, UserRole
from app.models.tenant import Tenant
from app.schemas.billing import InvoiceRead, PlanRead, SubscriptionCreate, SubscriptionRead, UsageRead, WalletRead, WalletCredit
from app.services.billing import BillingService
from app.core.config import settings

router = APIRouter(prefix="/billing", tags=["billing"])


def _service(session: Session) -> BillingService:
    return BillingService(session)


@router.get("/plans", response_model=List[PlanRead])
def list_plans(session: Session = Depends(get_db)) -> List[PlanRead]:
    service = _service(session)
    plans = service.list_active_plans()
    if not plans:
        plans = service.ensure_default_plans()
    return [PlanRead.model_validate(plan) for plan in plans]


@router.get("/subscription", response_model=SubscriptionRead)
def get_subscription(
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> SubscriptionRead:
    service = _service(session)
    subscription = service.get_subscription(current_user.tenant_id)
    if not subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
    return SubscriptionRead.model_validate(subscription)


@router.post("/subscription", response_model=SubscriptionRead, status_code=status.HTTP_201_CREATED)
def create_or_update_subscription(
    payload: SubscriptionCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> SubscriptionRead:
    service = _service(session)
    try:
        subscription = service.create_or_update_subscription(current_user.tenant_id, payload.plan_id, payload.payment_method_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SubscriptionRead.model_validate(subscription)


@router.get("/invoices", response_model=List[InvoiceRead])
def list_invoices(
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> List[InvoiceRead]:
    service = _service(session)
    invoices = service.list_invoices(current_user.tenant_id)
    return [InvoiceRead.model_validate(invoice) for invoice in invoices]


@router.post("/invoices/{invoice_id}/retry", response_model=InvoiceRead)
def retry_invoice(
    invoice_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> InvoiceRead:
    service = _service(session)
    try:
        invoice = service.retry_invoice(tenant_id=current_user.tenant_id, invoice_id=invoice_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return InvoiceRead.model_validate(invoice)


@router.get("/usage", response_model=UsageRead)
def get_usage(
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> UsageRead:
    service = _service(session)
    data = service.get_usage(current_user.tenant_id)
    return UsageRead.model_validate(data)


@router.post("/seed-plans", response_model=List[PlanRead], status_code=status.HTTP_201_CREATED)
def seed_default_plans(
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> List[PlanRead]:
    service = _service(session)
    plans = service.ensure_default_plans()
    return [PlanRead.model_validate(plan) for plan in plans]


@router.get("/wallet", response_model=WalletRead)
def get_wallet(
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> WalletRead:
    tenant = session.get(Tenant, current_user.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return WalletRead(balance_cents=tenant.balance_cents)


@router.post("/wallet/credit", response_model=WalletRead, status_code=status.HTTP_201_CREATED)
def credit_wallet(
    payload: WalletCredit,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> WalletRead:
    tenant = session.get(Tenant, current_user.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    amount = int(max(payload.amount_cents, 0))
    tenant.balance_cents = int(tenant.balance_cents or 0) + amount
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return WalletRead(balance_cents=tenant.balance_cents)


@router.post("/webhook/stripe", status_code=status.HTTP_200_OK)
async def stripe_webhook(request: Request, session: Session = Depends(get_db)) -> dict:
    """Stripe webhook with signature verification using Stripe-Signature header.

    We implement a minimal verifier compatible with Stripe's scheme: t=timestamp,v1=signature.
    The signed payload is: "{timestamp}.{raw_body}" and HMAC SHA256 with the webhook secret.
    """
    raw_body = await request.body()
    sig_header = request.headers.get("Stripe-Signature")
    if settings.stripe_webhook_secret:
        if not sig_header:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Stripe-Signature")
        try:
            parts = dict(kv.split("=", 1) for kv in sig_header.split(","))
            t = parts.get("t")
            v1 = parts.get("v1")
            if not t or not v1:
                raise ValueError("Invalid signature header")
            signed_payload = f"{t}.{raw_body.decode('utf-8')}".encode("utf-8")
            computed = hmac.new(settings.stripe_webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(computed, v1):
                raise ValueError("Signature mismatch")
            # Optional: tolerate 5 minutes skew
            if abs(int(time.time()) - int(t)) > 300:
                raise ValueError("Timestamp outside tolerance")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid signature: {exc}") from exc

    payload = await request.json()
    external_id = payload.get("data", {}).get("object", {}).get("id") or payload.get("external_id")
    event_type = payload.get("type") or payload.get("event")
    status_hint = "paid" if event_type in {"invoice.payment_succeeded", "charge.succeeded"} else "processing"
    # Extrai campos fiscais se presentes
    fiscal_fields = {}
    obj = payload.get("data", {}).get("object", {})
    for k in ["tax_id", "receipt_url", "fiscal_note_number"]:
        v = obj.get(k) or payload.get(k)
        if v:
            fiscal_fields[k] = v
    if external_id:
        BillingService(session).reconcile_payment(external_id=external_id, status=status_hint, extra_fields=fiscal_fields)
    return {"ok": True}


@router.post("/webhook/pagseguro", status_code=status.HTTP_200_OK)
async def pagseguro_webhook(request: Request, session: Session = Depends(get_db)) -> dict:
    """PagSeguro webhook with optional token validation.

    If settings.pagseguro_token is set, require Authorization Bearer with the same token.
    """
    if settings.pagseguro_token:
        auth = request.headers.get("Authorization")
        if not auth or not auth.lower().startswith("bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
        token = auth.split(" ", 1)[1]
        if token != settings.pagseguro_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    payload = await request.json()
    external_id = payload.get("external_reference") or payload.get("id")
    status_hint = payload.get("status") or "processing"
    # Extrai campos fiscais se presentes
    fiscal_fields = {}
    for k in ["tax_id", "receipt_url", "fiscal_note_number"]:
        v = payload.get(k)
        if v:
            fiscal_fields[k] = v
    if external_id:
        BillingService(session).reconcile_payment(external_id=external_id, status=status_hint, extra_fields=fiscal_fields)
    return {"ok": True}
