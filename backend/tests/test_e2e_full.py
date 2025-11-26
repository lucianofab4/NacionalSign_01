from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient


def _register_admin(client: TestClient) -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:8]
    payload = {
        "tenant_name": "Empresa E2E",
        "tenant_slug": f"e2e-{suffix}",
        "admin_full_name": "Admin Demo",
        "admin_email": f"admin+{suffix}@demo.com",
        "admin_cpf": "12345678901",
        "admin_password": "admin123",
        "cnpj": "12345678000199",
    }
    resp = client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code in (200, 201), resp.json()
    token = resp.json().get("access_token")
    assert token
    return token, payload["tenant_slug"]


def _bootstrap_tenant_and_area(client: TestClient) -> tuple[str, str, str]:
    token, slug = _register_admin(client)
    headers = {"Authorization": f"Bearer {token}"}

    me_resp = client.get("/api/v1/users/me", headers=headers)
    assert me_resp.status_code == 200, me_resp.json()
    me_data = me_resp.json()
    tenant_id = me_data["tenant_id"]
    default_area = me_data.get("default_area_id")

    if default_area:
        area_id = default_area
    else:
        area_resp = client.post(
            "/api/v1/tenants/areas",
            json={
                "name": f"Juridico-{uuid.uuid4().hex[:6]}",
                "description": "Area de testes",
            },
            headers=headers,
        )
        assert area_resp.status_code in (200, 201), area_resp.json()
        area_id = area_resp.json()["id"]

    return token, tenant_id, area_id


@pytest.mark.order(1)
def test_admin_register_and_login(client: TestClient) -> None:
    token, _ = _register_admin(client)
    assert token


@pytest.mark.order(2)
def test_create_tenant_and_area(client: TestClient) -> None:
    token, tenant_id, area_id = _bootstrap_tenant_and_area(client)
    assert token
    assert tenant_id
    assert area_id


@pytest.mark.order(3)
def test_document_workflow(client: TestClient) -> None:
    token, tenant_id, area_id = _bootstrap_tenant_and_area(client)
    headers = {"Authorization": f"Bearer {token}"}

    resp_doc = client.post(
        "/api/v1/documents",
        json={
            "name": "Contrato E2E",
            "area_id": area_id,
        },
        headers=headers,
    )
    assert resp_doc.status_code in (200, 201), resp_doc.json()
    doc_id = resp_doc.json()["id"]

    resp_party = client.post(
        f"/api/v1/documents/{doc_id}/parties",
        json={
            "full_name": "Usuario Signatario",
            "email": "signatario@demo.com",
            "role": "signer",
            "order_index": 1,
        },
        headers=headers,
    )
    assert resp_party.status_code in (200, 201), resp_party.json()

    from pathlib import Path

    sample_path = Path(__file__).resolve().parent / "assets" / "sample.pdf"
    with sample_path.open("rb") as f:
        resp_ver = client.post(
            f"/api/v1/documents/{doc_id}/versions",
            files={"file": ("sample.pdf", f, "application/pdf")},
            headers=headers,
        )
    assert resp_ver.status_code in (200, 201), resp_ver.json()

    version_id = resp_ver.json()["id"]
    resp_icp = client.get(f"/api/v1/documents/{doc_id}/versions/{version_id}", headers=headers)
    assert resp_icp.status_code == 200
    assert resp_icp.json()["icp_signed"]

    resp_audit = client.get(f"/api/v1/audit/events?document_id={doc_id}", headers=headers)
    assert resp_audit.status_code == 200

    resp_plans = client.get("/api/v1/billing/plans", headers=headers)
    assert resp_plans.status_code == 200
    plan_id = resp_plans.json()[0]["id"]

    resp_sub = client.post(
        "/api/v1/billing/subscription",
        json={
            "plan_id": plan_id,
            "payment_method_token": "tok_test",
        },
        headers=headers,
    )
    assert resp_sub.status_code in (200, 201), resp_sub.json()

    resp_inv = client.get("/api/v1/billing/invoices", headers=headers)
    assert resp_inv.status_code == 200

    resp_usage = client.get("/api/v1/billing/usage", headers=headers)
    assert resp_usage.status_code == 200

