from __future__ import annotations

from uuid import UUID

from fastapi import status

from app.core.config import settings
from app.models.tenant import Area, Tenant
from app.models.user import User
from app.models.document import Document, DocumentStatus
from tests.conftest import auth_headers, register_and_login  # type: ignore


def test_billing_usage_endpoint_counts_and_quota(client, db_session) -> None:
    token, email = register_and_login(client, email="admin@example.com", password="secret123")

    # Seed default plans (ADMIN only)
    resp_seed = client.post(f"{settings.api_v1_str}/billing/seed-plans", headers=auth_headers(token))
    assert resp_seed.status_code in {status.HTTP_200_OK, status.HTTP_201_CREATED}, resp_seed.text

    # List plans and pick the basic (smallest quotas) to make assertions deterministic
    resp_plans = client.get(f"{settings.api_v1_str}/billing/plans")
    assert resp_plans.status_code == status.HTTP_200_OK, resp_plans.text
    plans = sorted(resp_plans.json(), key=lambda p: p["price_monthly"])  # ascending by price
    assert plans, "expected at least one plan"
    basic = plans[0]

    # Create subscription for tenant
    payload = {"plan_id": basic["id"], "payment_method_token": "tok_test"}
    resp_sub = client.post(
        f"{settings.api_v1_str}/billing/subscription",
        json=payload,
        headers=auth_headers(token),
    )
    assert resp_sub.status_code in {status.HTTP_200_OK, status.HTTP_201_CREATED}, resp_sub.text

    # Identify tenant/user from DB and create a few documents to affect usage
    user: User = db_session.query(User).filter(User.email == email).first()  # type: ignore
    assert user is not None
    tenant_id: UUID = user.tenant_id

    area = Area(name="Area Teste", tenant_id=tenant_id)
    db_session.add(area)
    db_session.commit()

    # Create 3 documents for this tenant/area
    docs = [
        Document(tenant_id=tenant_id, area_id=area.id, name=f"Doc {i}", status=DocumentStatus.DRAFT, created_by_id=user.id)
        for i in range(3)
    ]
    db_session.add_all(docs)
    db_session.commit()

    # Call usage endpoint
    resp_usage = client.get(f"{settings.api_v1_str}/billing/usage", headers=auth_headers(token))
    assert resp_usage.status_code == status.HTTP_200_OK, resp_usage.text
    usage = resp_usage.json()

    assert usage["tenant_id"] == str(tenant_id)
    assert usage["documents_used"] >= 3
    assert usage["users_used"] >= 1
    # Quotas should reflect the chosen plan
    assert usage["documents_quota"] == basic["document_quota"]
    assert usage["users_quota"] == basic["user_quota"]
