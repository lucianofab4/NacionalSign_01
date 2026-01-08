from __future__ import annotations

import pytest
from uuid import uuid4
from sqlmodel import Session

from app.models.billing import Plan, Subscription
from app.models.tenant import Tenant, Area
from app.models.user import User, UserRole
from app.schemas.document import DocumentCreate
from app.schemas.user import UserCreate
from app.services.document import DocumentService
from app.services.user import UserService


@pytest.fixture()
def tenant_with_plan(db_session: Session):
    tenant = Tenant(name="Tenant", slug=f"tenant-{uuid4().hex[:6]}")
    plan = Plan(name="Mini", document_quota=2, user_quota=2, price_monthly=1000, price_yearly=10000, is_active=True)
    db_session.add_all([tenant, plan])
    db_session.flush()

    area = Area(name="Area", tenant_id=tenant.id)
    owner = User(
        tenant_id=tenant.id,
        email=f"owner_{uuid4().hex[:6]}@example.com",
        cpf="12345678901",
        full_name="Owner",
        password_hash="hash",
        profile=UserRole.ADMIN.value,
        default_area_id=area.id,
    )
    subscription = Subscription(tenant_id=tenant.id, plan_id=plan.id, status="active")

    db_session.add_all([area, subscription, owner])
    db_session.commit()
    return {"tenant": tenant, "area": area, "plan": plan, "subscription": subscription, "owner": owner}


def test_document_quota_enforced(db_session: Session, tenant_with_plan):
    svc = DocumentService(db_session)
    t = tenant_with_plan["tenant"]
    a = tenant_with_plan["area"]
    u = tenant_with_plan["owner"]

    # create up to the limit
    for i in range(2):
        doc = svc.create_document(
            t.id,
            u.id,
            DocumentCreate(area_id=a.id, name=f"Doc {i}"),
        )
        assert doc is not None

    # Next should fail
    with pytest.raises(ValueError, match="quota"):
        svc.create_document(t.id, u.id, DocumentCreate(area_id=a.id, name="Doc 3"))


def test_user_quota_is_unlimited(db_session: Session, tenant_with_plan):
    svc = UserService(db_session)
    t = tenant_with_plan["tenant"]
    a = tenant_with_plan["area"]

    payload = lambda i: UserCreate(
        email=f"user{i}_{uuid4().hex[:4]}@example.com",
        cpf=f"{i:011d}",
        full_name=f"User {i}",
        password="secret",
        profile=UserRole.USER,
        default_area_id=a.id,
    )

    # Deve permitir criar quantos usuários forem necessários
    for i in range(1, 5):
        user = svc.create_user(t.id, payload(i))
        assert user is not None


def test_user_creation_requires_deliverable_email(db_session: Session, tenant_with_plan):
    svc = UserService(db_session)
    tenant = tenant_with_plan["tenant"]
    area = tenant_with_plan["area"]

    payload = UserCreate(
        email="user@nonexistent-unittest-domain-123456.com",
        cpf="00000000000",
        full_name="Usuário Teste",
        password="secret",
        profile=UserRole.USER,
        default_area_id=area.id,
    )

    with pytest.raises(ValueError, match="E-mail inválido"):
        svc.create_user(tenant.id, payload)

def test_user_email_is_unique_per_tenant(db_session: Session):
    svc = UserService(db_session)

    tenant1 = Tenant(name="Tenant One", slug=f"tenant-one-{uuid4().hex[:6]}")
    db_session.add(tenant1)
    db_session.flush()
    area1 = Area(name="Area One", tenant_id=tenant1.id)
    db_session.add(area1)
    db_session.commit()

    tenant2 = Tenant(name="Tenant Two", slug=f"tenant-two-{uuid4().hex[:6]}")
    db_session.add(tenant2)
    db_session.flush()
    area2 = Area(name="Area Two", tenant_id=tenant2.id)
    db_session.add(area2)
    db_session.commit()

    shared_email = "duplicado@example.com"

    svc.create_user(
        tenant1.id,
        UserCreate(
            email=shared_email,
            cpf="12312312300",
            full_name="Usuário A",
            password="secret",
            profile=UserRole.USER,
            default_area_id=area1.id,
        ),
    )

    svc.create_user(
        tenant2.id,
        UserCreate(
            email=shared_email,
            cpf="32132132100",
            full_name="Usuário B",
            password="secret",
            profile=UserRole.USER,
            default_area_id=area2.id,
        ),
    )

    with pytest.raises(ValueError, match="e-mail"):
        svc.create_user(
            tenant1.id,
            UserCreate(
                email=shared_email,
                cpf="99999999999",
                full_name="Usuário C",
                password="secret",
                profile=UserRole.USER,
                default_area_id=area1.id,
            ),
        )


def test_user_creation_accepts_blank_cpf(db_session: Session, tenant_with_plan):
    svc = UserService(db_session)
    tenant = tenant_with_plan["tenant"]
    area = tenant_with_plan["area"]

    user = svc.create_user(
        tenant.id,
        UserCreate(
            email="blankcpf@example.com",
            cpf="",
            full_name="Usuário Sem CPF",
            password="secret",
            profile=UserRole.USER,
            default_area_id=area.id,
        ),
    )
    assert user.cpf is None


def test_tenant_max_documents_override_plan_quota(db_session: Session, tenant_with_plan):
    svc = DocumentService(db_session)
    tenant = tenant_with_plan["tenant"]
    area = tenant_with_plan["area"]
    user = tenant_with_plan["owner"]

    tenant.max_documents = 4
    db_session.add(tenant)
    db_session.commit()

    for i in range(4):
        doc = svc.create_document(
            tenant.id,
            user.id,
            DocumentCreate(area_id=area.id, name=f"Doc extra {i}"),
        )
        assert doc is not None

    with pytest.raises(ValueError, match="quota"):
        svc.create_document(
            tenant.id,
            user.id,
            DocumentCreate(area_id=area.id, name="Doc limite"),
        )
