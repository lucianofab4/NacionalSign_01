from uuid import uuid4

from app.models.billing import Plan
from app.models.tenant import Tenant
from app.services.billing import BillingService, ManualGateway, StripeGateway


def _make_plan() -> Plan:
    return Plan(
        name="Pro",
        document_quota=100,
        user_quota=10,
        price_monthly=19900,
        price_yearly=199000,
        is_active=True,
    )


def _make_tenant() -> Tenant:
    slug = f"tenant-{uuid4().hex[:6]}"
    return Tenant(name="Tenant", slug=slug)


def test_billing_subscription_manual_gateway(db_session):
    plan = _make_plan()
    tenant = _make_tenant()
    db_session.add_all([plan, tenant])
    db_session.commit()

    service = BillingService(db_session, gateway=ManualGateway())

    subscription = service.create_or_update_subscription(tenant.id, plan.id, payment_token="tok_manual")

    assert subscription.plan_id == plan.id
    assert subscription.status in {"pending", "processing"}
    assert subscription.auto_renew is True
    assert subscription.valid_until is not None

    invoices = list(service.list_invoices(tenant.id))
    assert len(invoices) == 1
    invoice = invoices[0]
    assert invoice.gateway == "manual"
    assert invoice.amount_cents == plan.price_monthly


def test_billing_subscription_stripe_gateway_marks_paid(db_session):
    plan = _make_plan()
    tenant = _make_tenant()
    db_session.add_all([plan, tenant])
    db_session.commit()

    service = BillingService(db_session, gateway=StripeGateway(api_key="sk_test"))

    subscription = service.create_or_update_subscription(tenant.id, plan.id, payment_token="tok_stripe")

    assert subscription.status == "active"

    invoices = list(service.list_invoices(tenant.id))
    assert len(invoices) == 1
    assert invoices[0].status == "paid"
    assert invoices[0].paid_at is not None
