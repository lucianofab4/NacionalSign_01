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


def test_user_quota_enforced(db_session: Session, tenant_with_plan):
    svc = UserService(db_session)
    t = tenant_with_plan["tenant"]
    a = tenant_with_plan["area"]

    # create up to the limit (already have 1 owner)
    payload = lambda i: UserCreate(
        email=f"user{i}_{uuid4().hex[:4]}@example.com",
        cpf="00000000000",
        full_name=f"User {i}",
        password="secret",
        profile=UserRole.USER,
        default_area_id=a.id,
    )

    user1 = svc.create_user(t.id, payload(1))
    assert user1 is not None

    # At this point users count is 2 (owner + user1). One more should exceed quota=2
    with pytest.raises(ValueError, match="quota"):
        svc.create_user(t.id, payload(2))
