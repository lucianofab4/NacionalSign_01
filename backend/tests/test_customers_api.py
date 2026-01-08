from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import status
from sqlmodel import Session, select

from app.core.config import settings
from app.models.billing import Plan, Subscription
from app.models.customer import Customer
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from tests.conftest import auth_headers, register_and_login  # type: ignore


def _prepare_owner_token(client, db_session: Session, monkeypatch):
    monkeypatch.setattr(settings, "customer_admin_emails", [])
    token, admin_email = register_and_login(client, email="owner@example.com", password="Senha@123")
    settings.customer_admin_emails = [admin_email]
    owner_user = db_session.exec(select(User).where(User.email == admin_email)).first()
    assert owner_user is not None
    owner_user.profile = UserRole.OWNER.value
    db_session.add(owner_user)
    db_session.commit()
    login_response = client.post(
        f"{settings.api_v1_str}/auth/login",
        json={"username": admin_email, "password": "Senha@123"},
    )
    assert login_response.status_code == status.HTTP_200_OK
    return login_response.json()


def _seed_customer_with_subscription(db_session: Session) -> dict[str, object]:
    plan = Plan(
        name="Pro 50",
        document_quota=50,
        user_quota=10,
        price_monthly=9900,
        price_yearly=99900,
        is_active=True,
    )
    db_session.add(plan)
    db_session.flush()

    tenant = Tenant(
        name="Cliente Plano",
        slug=f"cliente-{uuid4().hex[:6]}",
        plan_id=str(plan.id),
        max_documents=plan.document_quota,
    )
    db_session.add(tenant)
    db_session.flush()

    subscription = Subscription(
        tenant_id=tenant.id,
        plan_id=plan.id,
        status="active",
        valid_until=datetime.utcnow() + timedelta(days=5),
    )
    customer = Customer(
        corporate_name="Cliente Plano LTDA",
        trade_name="Cliente Plano",
        cnpj="44556677000188",
        responsible_name="João Plano",
        responsible_email="joao@cliente.com",
        responsible_phone="+55 11 93333-0000",
        tenant_id=tenant.id,
        plan_id=plan.id,
        document_quota=plan.document_quota,
        activation_token=str(uuid4()),
    )
    db_session.add_all([subscription, customer])
    db_session.commit()
    return {"plan": plan, "tenant": tenant, "subscription": subscription, "customer": customer}


def test_get_my_company_profile_flow(client, db_session: Session) -> None:
    token, email = register_and_login(client, email="empresa@example.com", password="Senha@123")
    response = client.get(f"{settings.api_v1_str}/customers/me", headers=auth_headers(token))
    assert response.status_code == status.HTTP_404_NOT_FOUND

    tenant = db_session.exec(select(Tenant).where(Tenant.slug.like("empresa-%"))).first()
    assert tenant is not None

    admin_user = db_session.exec(select(User).where(User.email == email)).first()
    assert admin_user is not None

    customer = Customer(
        corporate_name="Empresa Teste LTDA",
        trade_name="Empresa Teste",
        cnpj="12345678000199",
        responsible_name="Maria Responsável",
        responsible_email="maria@example.com",
        responsible_phone="+55 11 99999-0000",
        tenant_id=tenant.id,
        document_quota=50,
        activation_token=str(uuid4()),
    )
    db_session.add(customer)
    db_session.commit()

    success_response = client.get(f"{settings.api_v1_str}/customers/me", headers=auth_headers(token))
    assert success_response.status_code == status.HTTP_200_OK, success_response.json()
    payload = success_response.json()
    assert payload["corporate_name"] == "Empresa Teste LTDA"
    assert payload["trade_name"] == "Empresa Teste"
    assert payload["cnpj"] == "12345678000199"
    assert payload["responsible_name"] == "Maria Responsável"


def test_owner_can_delete_customer(client, db_session: Session, monkeypatch) -> None:
    token = _prepare_owner_token(client, db_session, monkeypatch)

    customer = Customer(
        corporate_name="Cliente Temporário",
        trade_name="Cliente Temp",
        cnpj="99887766000155",
        responsible_name="Fulano",
        responsible_email="fulano@example.com",
        responsible_phone="+55 11 97777-0000",
        activation_token="token",
    )
    db_session.add(customer)
    db_session.commit()

    delete_response = client.delete(
        f"{settings.api_v1_str}/customers/{customer.id}",
        headers=auth_headers(token),
    )
    assert delete_response.status_code == status.HTTP_204_NO_CONTENT
    with Session(db_session.get_bind()) as verify_session:  # type: ignore[arg-type]
        assert verify_session.get(Customer, customer.id) is None


def test_owner_can_grant_documents(client, db_session: Session, monkeypatch) -> None:
    token = _prepare_owner_token(client, db_session, monkeypatch)
    records = _seed_customer_with_subscription(db_session)
    customer: Customer = records["customer"]  # type: ignore[assignment]
    tenant: Tenant = records["tenant"]  # type: ignore[assignment]

    response = client.post(
        f"{settings.api_v1_str}/customers/{customer.id}/grant-documents",
        json={"amount": 15},
        headers=auth_headers(token),
    )
    assert response.status_code == status.HTTP_200_OK, response.json()
    payload = response.json()
    assert payload["document_quota"] == 65

    db_session.expire_all()
    refreshed_customer = db_session.get(Customer, customer.id)
    assert refreshed_customer is not None
    assert refreshed_customer.document_quota == 65
    refreshed_tenant = db_session.get(Tenant, tenant.id)
    assert refreshed_tenant is not None
    assert refreshed_tenant.max_documents == 65


def test_owner_can_renew_customer_plan(client, db_session: Session, monkeypatch) -> None:
    token = _prepare_owner_token(client, db_session, monkeypatch)
    records = _seed_customer_with_subscription(db_session)
    customer: Customer = records["customer"]  # type: ignore[assignment]
    tenant: Tenant = records["tenant"]  # type: ignore[assignment]

    subscription = db_session.exec(
        select(Subscription).where(Subscription.tenant_id == tenant.id)
    ).first()
    assert subscription is not None and subscription.valid_until is not None
    previous_valid_until = subscription.valid_until

    response = client.post(
        f"{settings.api_v1_str}/customers/{customer.id}/renew-plan",
        json={"days": 15},
        headers=auth_headers(token),
    )
    assert response.status_code == status.HTTP_200_OK, response.json()

    db_session.expire_all()
    refreshed_subscription = db_session.get(Subscription, subscription.id)
    assert refreshed_subscription is not None
    assert refreshed_subscription.valid_until is not None
    assert refreshed_subscription.valid_until > previous_valid_until
