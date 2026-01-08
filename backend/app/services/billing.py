from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Protocol
from uuid import UUID

from sqlmodel import Session, select, func

from app.core.config import settings
from app.models.billing import Invoice, Plan, Subscription
from app.models.tenant import Tenant
from app.models.document import Document, DocumentStatus
from app.models.user import User
from app.models.client import Client


@dataclass
class PaymentResult:
    external_id: str
    status: str
    paid: bool


class PaymentGateway(Protocol):
    name: str

    def charge(self, *, tenant_id: UUID, plan: Plan, payment_token: str) -> PaymentResult:
        ...


class ManualGateway:
    name = "manual"

    def charge(self, *, tenant_id: UUID, plan: Plan, payment_token: str) -> PaymentResult:  # noqa: D401
        return PaymentResult(
            external_id=f"manual-{uuid.uuid4().hex[:12]}",
            status="pending",
            paid=False,
        )


class StripeGateway:
    name = "stripe"

    def __init__(self, api_key: str) -> None:  # noqa: D401
        self.api_key = api_key

    def charge(self, *, tenant_id: UUID, plan: Plan, payment_token: str) -> PaymentResult:  # noqa: D401
        # Real implementation should call Stripe's PaymentIntent API.
        # For the MVP we acknowledge the payment token and mark the invoice as paid.
        return PaymentResult(
            external_id=f"stripe-{uuid.uuid4().hex[:12]}",
            status="paid",
            paid=True,
        )


class PagSeguroGateway:
    name = "pagseguro"

    def __init__(self, token: str, app_id: str | None = None) -> None:  # noqa: D401
        self.token = token
        self.app_id = app_id

    def charge(self, *, tenant_id: UUID, plan: Plan, payment_token: str) -> PaymentResult:  # noqa: D401
        # Real implementation should call PagSeguro's subscription API.
        # We immediately move the invoice to processing so finance can reconcile later.
        return PaymentResult(
            external_id=f"pg-{uuid.uuid4().hex[:12]}",
            status="processing",
            paid=False,
        )


class BillingService:
    def __init__(self, session: Session, gateway: PaymentGateway | None = None) -> None:
        self.session = session
        self.gateway = gateway or self._gateway_from_settings()

    def _gateway_from_settings(self) -> PaymentGateway:
        gateway_name = (settings.billing_default_gateway or "manual").lower()
        if gateway_name == "stripe" and settings.stripe_api_key:
            return StripeGateway(settings.stripe_api_key)
        if gateway_name == "pagseguro" and settings.pagseguro_token:
            return PagSeguroGateway(settings.pagseguro_token, settings.pagseguro_app_id)
        return ManualGateway()

    def list_active_plans(self) -> Iterable[Plan]:
        return self.session.exec(
            select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.price_monthly)
        ).all()

    def get_subscription(self, tenant_id: UUID) -> Subscription | None:
        subscription = self.session.exec(
            select(Subscription).where(Subscription.tenant_id == tenant_id)
        ).first()
        if subscription:
            return subscription
        tenant = self.session.get(Tenant, tenant_id)
        if not tenant or not tenant.plan_id:
            return None
        try:
            plan_id = UUID(str(tenant.plan_id))
        except (TypeError, ValueError):
            return None
        plan = self.session.get(Plan, plan_id)
        if not plan:
            return None
        subscription = Subscription(
            tenant_id=tenant_id,
            plan_id=plan.id,
            status="active",
            valid_until=None,
            auto_renew=False,
        )
        self.session.add(subscription)
        self.session.commit()
        self.session.refresh(subscription)
        return subscription

    def list_invoices(self, tenant_id: UUID) -> Iterable[Invoice]:
        return self.session.exec(
            select(Invoice)
            .where(Invoice.tenant_id == tenant_id)
            .order_by(Invoice.created_at.desc())
        ).all()

    def get_invoice(self, invoice_id: UUID) -> Invoice | None:
        return self.session.get(Invoice, invoice_id)

    def _compute_backoff_delay(self, attempt: int) -> timedelta:
        """Exponential backoff schedule for payment retries.

        attempt is 1-based (after increment). We use a simple stepped backoff:
        1 -> 15 minutes, 2 -> 1 hour, 3 -> 6 hours, 4+ -> 24 hours.
        """
        if attempt <= 1:
            return timedelta(minutes=15)
        if attempt == 2:
            return timedelta(hours=1)
        if attempt == 3:
            return timedelta(hours=6)
        return timedelta(hours=24)

    def retry_invoice(self, *, tenant_id: UUID, invoice_id: UUID) -> Invoice:
        """Lightweight retry: move non-paid invoice back to 'processing' and bump due_date.

        This is a placeholder for real gateway re-attempts. Finance can reconcile via webhook later.
        """
        invoice = self.get_invoice(invoice_id)
        if not invoice or invoice.tenant_id != tenant_id:
            raise ValueError("Invoice not found")
        if invoice.status == "paid":
            return invoice
        now = datetime.utcnow()
        if getattr(invoice, "retry_count", 0) >= max(getattr(settings, "billing_max_retries", 3), 1):
            # Exceeded retry budget; mark as failed and do not move back to processing
            invoice.status = "failed"
            invoice.last_attempt_at = datetime.utcnow()
            self.session.add(invoice)
            self.session.commit()
            self.session.refresh(invoice)
            return invoice
        invoice.status = "processing"
        invoice.paid_at = None
        invoice.retry_count = int(getattr(invoice, "retry_count", 0) or 0) + 1
        invoice.last_attempt_at = now
        # Set next attempt using exponential backoff and reset due date to now
        invoice.next_attempt_at = now + self._compute_backoff_delay(invoice.retry_count)
        invoice.due_date = now
        self.session.add(invoice)
        self.session.commit()
        self.session.refresh(invoice)
        return invoice

    def get_usage(
        self,
        tenant_id: UUID,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, object]:
        subscription = self.get_subscription(tenant_id)

        def _strip_tz(value: datetime | None) -> datetime | None:
            if not value:
                return None
            return value.replace(tzinfo=None)

        now = datetime.utcnow().replace(tzinfo=None)
        if start_date or end_date:
            period_end = _strip_tz(end_date) or now
            period_start = _strip_tz(start_date) or (period_end - timedelta(days=30))
        elif subscription and subscription.valid_until:
            period_end = _strip_tz(subscription.valid_until) or now
            period_start = period_end - timedelta(days=30)
        else:
            period_end = now
            period_start = now - timedelta(days=30)

        if period_start > period_end:
            period_start, period_end = period_end, period_start

        docs_count = self.session.exec(
            select(func.count())
            .select_from(Document)
            .where(
                (Document.tenant_id == tenant_id)
                & (Document.created_at >= period_start)
                & (Document.created_at <= period_end)
            )
        ).one()
        signed_count = self.session.exec(
            select(func.count())
            .select_from(Document)
            .where(
                (Document.tenant_id == tenant_id)
                & (Document.status == DocumentStatus.COMPLETED)
                & (func.coalesce(Document.updated_at, Document.created_at) >= period_start)
                & (func.coalesce(Document.updated_at, Document.created_at) <= period_end)
            )
        ).one()
        users_count = self.session.exec(
            select(func.count()).select_from(User).where(User.tenant_id == tenant_id)
        ).one()

        plan = self.session.get(Plan, subscription.plan_id) if subscription else None
        tenant = self.session.get(Tenant, tenant_id)
        documents_used = int(docs_count or 0)
        documents_signed = int(signed_count or 0)
        users_used = int(users_count or 0)

        manual_quota = None
        if tenant and tenant.max_documents and tenant.max_documents > 0:
            manual_quota = int(tenant.max_documents)
        doc_quota = manual_quota if manual_quota is not None else (plan.document_quota if plan else None)
        # Planos atuais não limitam usuários; mantemos None para refletir "ilimitado"
        user_quota = None

        def _percent(used: int, quota: int | None) -> float | None:
            if quota is None or quota <= 0:
                return None
            return round(min(used / float(quota) * 100.0, 999.0), 2)

        documents_percent = _percent(documents_used, doc_quota)
        documents_signed_percent = _percent(documents_signed, doc_quota)
        users_percent = _percent(users_used, user_quota)

        near_limit = False
        msg_parts: list[str] = []
        if documents_percent is not None and documents_percent >= 80.0:
            near_limit = True
            msg_parts.append(f"Voce usou {documents_used}/{doc_quota} documentos do seu plano.")
        if users_percent is not None and users_percent >= 80.0:
            near_limit = True
            msg_parts.append(f"Voce usou {users_used}/{user_quota} usuarios do seu plano.")
        message = " ".join(msg_parts) if msg_parts else None

        return {
            'tenant_id': tenant_id,
            'period_start': period_start,
            'period_end': period_end,
            'documents_used': documents_used,
            'documents_signed': documents_signed,
            'documents_quota': doc_quota,
            'users_used': users_used,
            'users_quota': user_quota,
            'documents_percent': documents_percent,
            'documents_signed_percent': documents_signed_percent,
            'users_percent': users_percent,
            'near_limit': near_limit,
            'message': message,
        }

    def list_usage_overview(
        self,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
        threshold: float = 0.8,
        include_inactive: bool = False,
        include_empty: bool = False,
    ) -> dict[str, object]:
        now = datetime.utcnow().replace(tzinfo=None)
        period_end = (end_date or now).replace(tzinfo=None)
        period_start = (start_date or (period_end - timedelta(days=30))).replace(tzinfo=None)
        if period_start > period_end:
            period_start, period_end = period_end, period_start

        normalized_threshold = max(0.1, min(threshold or 0.8, 0.99))

        conditions = []
        if not include_inactive:
            conditions.append(Tenant.is_active.is_(True))
        if search:
            normalized = f"%{search.strip().lower()}%"
            conditions.append(func.lower(Tenant.name).like(normalized))

        total_stmt = select(func.count()).select_from(Tenant)
        if conditions:
            total_stmt = total_stmt.where(*conditions)
        total = self.session.exec(total_stmt).one()

        stmt = select(Tenant)
        if conditions:
            stmt = stmt.where(*conditions)
        stmt = stmt.order_by(Tenant.created_at.desc()).offset(max(offset, 0)).limit(max(limit, 1))
        tenants = self.session.exec(stmt).all()
        tenant_ids = [tenant.id for tenant in tenants]

        subscription_map: dict[UUID, tuple[Subscription | None, Plan | None]] = {}
        client_map: dict[UUID, Client] = {}
        if tenant_ids:
            sub_stmt = (
                select(Subscription, Plan)
                .where(Subscription.tenant_id.in_(tenant_ids))
                .join(Plan, Plan.id == Subscription.plan_id, isouter=True)
            )
            for subscription, plan in self.session.exec(sub_stmt):
                subscription_map[subscription.tenant_id] = (subscription, plan)
            client_stmt = select(Client).where(Client.tenant_id.in_(tenant_ids)).order_by(Client.created_at.desc())
            for client in self.session.exec(client_stmt):
                client_map.setdefault(client.tenant_id, client)

        rows: list[dict[str, object]] = []
        alerts: list[dict[str, object]] = []

        for tenant in tenants:
            usage = self.get_usage(tenant.id, start_date=period_start, end_date=period_end)
            subscription, plan = subscription_map.get(tenant.id, (None, None))
            doc_quota = usage.get('documents_quota')
            documents_used = usage.get('documents_used', 0) or 0
            client = client_map.get(tenant.id)

            limit_state = 'unlimited' if not doc_quota else 'ok'
            limit_ratio = None
            if doc_quota:
                limit_ratio = float(documents_used) / float(doc_quota) if doc_quota else None
                if limit_ratio is not None:
                    if limit_ratio >= 1.0:
                        limit_state = 'exceeded'
                    elif limit_ratio >= normalized_threshold:
                        limit_state = 'near_limit'

            display_name = (client.name if client and getattr(client, "name", None) else None) or tenant.name
            row = {
                **usage,
                'tenant_name': display_name,
                'tenant_slug': tenant.slug,
                'plan_id': plan.id if plan else None,
                'plan_name': plan.name if plan else None,
                'subscription_status': subscription.status if subscription else None,
                'limit_state': limit_state,
                'limit_ratio': limit_ratio,
            }
            has_activity = (
                client is not None
                or (documents_used or 0) > 0
                or (usage.get('documents_signed') or 0) > 0
                or plan is not None
            )
            if not include_empty and not has_activity:
                continue
            rows.append(row)
            if limit_state in {'near_limit', 'exceeded'} or usage.get('near_limit'):
                alerts.append(row)

        return {
            'total': int(total or 0),
            'period_start': period_start,
            'period_end': period_end,
            'items': rows,
            'alerts': alerts,
        }

    def ensure_default_plans(self) -> list[Plan]:
        """Idempotently create default plans for MVP."""
        defaults = [
            ("Básico", 20, 3, 4900, 49000),
            ("Pro", 100, 10, 19900, 199000),
            ("Enterprise", 1000, 100, 99900, 999000),
        ]
        existing = {p.name: p for p in self.session.exec(select(Plan)).all()}
        created: list[Plan] = []
        for name, doc_q, user_q, m_price, y_price in defaults:
            plan = existing.get(name)
            if not plan:
                plan = Plan(
                    name=name,
                    document_quota=doc_q,
                    user_quota=user_q,
                    price_monthly=m_price,
                    price_yearly=y_price,
                    is_active=True,
                )
                self.session.add(plan)
                created.append(plan)
        if created:
            self.session.commit()
            for p in created:
                self.session.refresh(p)
        return self.session.exec(select(Plan).where(Plan.is_active.is_(True))).all()

    def reconcile_payment(self, *, external_id: str, status: str, extra_fields: dict = None) -> Invoice | None:
        """Update invoice (and related subscription) based on webhook callbacks. Preenche campos fiscais se presentes."""
        invoice = self.session.exec(select(Invoice).where(Invoice.external_id == external_id)).first()
        if not invoice:
            return None
        paid = status.lower() in {"paid", "succeeded", "approved"}
        invoice.status = "paid" if paid else status
        invoice.paid_at = datetime.utcnow() if paid else None
        # Preencher campos fiscais se presentes
        if extra_fields:
            for k in ["tax_id", "receipt_url", "fiscal_note_number"]:
                v = extra_fields.get(k)
                if v:
                    setattr(invoice, k, v)
        self.session.add(invoice)
        # Update subscription status to active if paid
        subscription = self.get_subscription(invoice.tenant_id)
        if subscription and paid:
            subscription.status = "active"
            # extend validity minimally by 30 days a partir de agora
            subscription.valid_until = datetime.utcnow() + timedelta(days=30)
            self.session.add(subscription)
        self.session.commit()
        self.session.refresh(invoice)
        return invoice

    def create_or_update_subscription(self, tenant_id: UUID, plan_id: UUID, payment_token: str) -> Subscription:
        plan = self.session.get(Plan, plan_id)
        if not plan or not plan.is_active:
            raise ValueError("Plan not available")

        payment = self.gateway.charge(tenant_id=tenant_id, plan=plan, payment_token=payment_token)

        subscription = self.get_subscription(tenant_id)
        now = datetime.utcnow()
        # Keep current cycle end if upgrading mid-cycle; otherwise start a new 30-day cycle (+ optional trial)
        if subscription and subscription.valid_until and subscription.valid_until > now:
            validity = subscription.valid_until
        else:
            validity = now + timedelta(days=30 + max(settings.billing_trial_days, 0))

        # Proration/ajuste para upgrade/downgrade
        proration_credit = 0
        ajuste_zero = False
        if subscription and subscription.plan_id != plan.id:
            old_plan = self.session.get(Plan, subscription.plan_id)
            if old_plan and subscription.valid_until:
                remaining_seconds = (subscription.valid_until - now).total_seconds()
                if remaining_seconds > 0:
                    fraction = min(remaining_seconds / float(timedelta(days=30).total_seconds()), 1.0)
                    # Se for upgrade (novo plano mais caro), calcula crédito do plano antigo
                    if old_plan.price_monthly < plan.price_monthly:
                        proration_credit = int(round(old_plan.price_monthly * fraction))
                    # Se for downgrade (novo plano mais barato), não cobra nada e marca ajuste_zero
                    elif old_plan.price_monthly > plan.price_monthly:
                        ajuste_zero = True
        if subscription:
            subscription.plan_id = plan.id
            subscription.status = "active" if payment.paid else payment.status
            subscription.valid_until = validity
            subscription.auto_renew = True
        else:
            subscription = Subscription(
                tenant_id=tenant_id,
                plan_id=plan.id,
                status="active" if payment.paid else payment.status,
                valid_until=validity,
                auto_renew=True,
            )
        self.session.add(subscription)

        # Se for downgrade, gera fatura de ajuste zero
        if ajuste_zero:
            invoice = Invoice(
                tenant_id=tenant_id,
                gateway=getattr(self.gateway, "name", "manual"),
                external_id=f"ajuste-{uuid.uuid4().hex[:12]}",
                amount_cents=0,
                due_date=now,
                status="paid",
                paid_at=now,
            )
            self.session.add(invoice)
        else:
            # Compute invoice amount considering proration credit (not below zero)
            amount_cents = max(plan.price_monthly - proration_credit, 0)
            invoice = Invoice(
                tenant_id=tenant_id,
                gateway=getattr(self.gateway, "name", "manual"),
                external_id=payment.external_id,
                amount_cents=amount_cents,
                due_date=now,
                status="paid" if payment.paid else payment.status,
                paid_at=now if payment.paid else None,
            )
            # If unpaid, schedule next_attempt_at for retry/dunning window
            if not payment.paid:
                try:
                    invoice.next_attempt_at = now + self._compute_backoff_delay(1)
                except Exception:
                    pass
            self.session.add(invoice)

        tenant = self.session.get(Tenant, tenant_id)
        if tenant:
            tenant.plan_id = str(plan.id)
            self.session.add(tenant)

        self.session.commit()
        self.session.refresh(subscription)
        return subscription
