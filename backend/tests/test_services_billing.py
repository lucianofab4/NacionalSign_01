from uuid import uuid4
from datetime import datetime, timedelta

from app.models.billing import Plan, Subscription
from app.models.tenant import Tenant, Area
from app.models.user import User, UserRole
from app.models.document import Document, DocumentStatus
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


def test_usage_overview_includes_signed_docs(db_session):
    plan = Plan(name="Mini", document_quota=1, user_quota=5, price_monthly=1000, price_yearly=10000, is_active=True)
    tenant = _make_tenant()
    db_session.add_all([plan, tenant])
    db_session.flush()

    area = Area(name="Area", tenant_id=tenant.id)
    user = User(
        tenant_id=tenant.id,
        email=f"{uuid4().hex[:6]}@example.com",
        cpf="12345678901",
        full_name="Owner",
        password_hash="hash",
        profile=UserRole.ADMIN.value,
        default_area_id=area.id,
    )
    subscription = Subscription(tenant_id=tenant.id, plan_id=plan.id, status="active")
    now = datetime.utcnow()
    start = now - timedelta(days=10)
    signed_doc = Document(
        tenant_id=tenant.id,
        area_id=area.id,
        name="Doc 1",
        created_by_id=user.id,
        status=DocumentStatus.COMPLETED,
        created_at=start + timedelta(days=1),
        updated_at=now,
    )
    pending_doc = Document(
        tenant_id=tenant.id,
        area_id=area.id,
        name="Doc 2",
        created_by_id=user.id,
        status=DocumentStatus.IN_PROGRESS,
        created_at=start + timedelta(days=2),
        updated_at=start + timedelta(days=2),
    )
    db_session.add_all([area, user, subscription, signed_doc, pending_doc])
    db_session.commit()

    service = BillingService(db_session)
    overview = service.list_usage_overview(start_date=start, end_date=now, threshold=0.5)
    assert overview["total"] >= 1
    assert overview["alerts"], "expected tenant near limit due to quota 1"
    row = overview["items"][0]
    assert row["documents_used"] == 2
    assert row["documents_signed"] == 1
    assert row["limit_state"] in {"near_limit", "exceeded"}


def test_usage_prefers_tenant_manual_quota(db_session):
    plan = Plan(name="Basic", document_quota=10, user_quota=5, price_monthly=1000, price_yearly=10000, is_active=True)
    tenant = _make_tenant()
    tenant.max_documents = 25
    db_session.add_all([plan, tenant])
    db_session.flush()
    subscription = Subscription(tenant_id=tenant.id, plan_id=plan.id, status="active")
    db_session.add(subscription)
    db_session.commit()

    service = BillingService(db_session)
    usage = service.get_usage(tenant.id)
    assert usage["documents_quota"] == 25
