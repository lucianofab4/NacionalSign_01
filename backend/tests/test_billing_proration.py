from __future__ import annotations

from uuid import uuid4

from app.models.billing import Plan
from app.models.tenant import Tenant
from app.services.billing import BillingService, ManualGateway


def _make_plan(name: str, price: int, docs: int, users: int) -> Plan:
    return Plan(
        name=name,
        document_quota=docs,
        user_quota=users,
        price_monthly=price,
        price_yearly=price * 10,
        is_active=True,
    )


def _make_tenant() -> Tenant:
    slug = f"tenant-{uuid4().hex[:6]}"
    return Tenant(name="Tenant", slug=slug)


def test_proration_applies_on_upgrade(db_session):
    basic = _make_plan("Basic", price=1000, docs=10, users=3)
    pro = _make_plan("Pro", price=2000, docs=100, users=10)
    tenant = _make_tenant()
    db_session.add_all([basic, pro, tenant])
    db_session.commit()

    service = BillingService(db_session, gateway=ManualGateway())

    # First subscribe to basic
    sub1 = service.create_or_update_subscription(tenant.id, basic.id, payment_token="tok_manual")
    invoices1 = list(service.list_invoices(tenant.id))
    assert invoices1[-1].amount_cents == basic.price_monthly

    # Now upgrade to pro mid-cycle: manual gateway returns pending, proration credit should reduce amount
    sub2 = service.create_or_update_subscription(tenant.id, pro.id, payment_token="tok_manual")
    invoices2 = list(service.list_invoices(tenant.id))
    last_invoice = invoices2[-1]
    assert last_invoice.amount_cents <= pro.price_monthly
    assert last_invoice.amount_cents >= pro.price_monthly - basic.price_monthly
