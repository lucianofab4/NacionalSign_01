from __future__ import annotations

from uuid import UUID

from fastapi import status
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models.billing import Invoice


def test_invoice_retry_endpoint(client: TestClient, db_session: Session):
    # Register and login as admin
    from tests.conftest import register_and_login, auth_headers

    token, _ = register_and_login(client, email="admin@example.com", password="secret123")
    headers = auth_headers(token)

    # Seed plans and pick one
    r = client.post(f"{settings.api_v1_str}/billing/seed-plans", headers=headers)
    assert r.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), r.text

    plans = client.get(f"{settings.api_v1_str}/billing/plans", headers=headers)
    assert plans.status_code == status.HTTP_200_OK
    plan_id = plans.json()[0]["id"]

    # Create subscription (Manual gateway in tests => invoice pending/processing, unpaid)
    sub = client.post(
        f"{settings.api_v1_str}/billing/subscription",
        headers=headers,
        json={"plan_id": plan_id, "payment_method_token": "tok_test"},
    )
    assert sub.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), sub.text

    # List invoices and pick first
    inv = client.get(f"{settings.api_v1_str}/billing/invoices", headers=headers)
    assert inv.status_code == status.HTTP_200_OK, inv.text
    data = inv.json()
    assert len(data) >= 1
    invoice_id = data[0]["id"]

    # Call retry endpoint
    retry = client.post(f"{settings.api_v1_str}/billing/invoices/{invoice_id}/retry", headers=headers)
    assert retry.status_code == status.HTTP_200_OK, retry.text
    body = retry.json()
    assert body["status"] == "processing"

    # Verify DB fields updated (retry_count, last_attempt_at)
    db_invoice = db_session.get(Invoice, UUID(invoice_id))
    assert db_invoice is not None
    assert db_invoice.retry_count >= 1
    assert db_invoice.last_attempt_at is not None
