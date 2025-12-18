from __future__ import annotations

import base64


from uuid import UUID

from fastapi import status
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.document import AuditArtifact, Document, DocumentParty, DocumentStatus
from app.models.signing import SigningAgentAttempt, SigningAgentAttemptStatus
from app.models.user import User, UserRole
from app.models.tenant import Area
from app.models.workflow import (
    Signature,
    SignatureRequest,
    SignatureRequestStatus,
    SignatureType,
    WorkflowInstance,
    WorkflowStatus,
    WorkflowStep,
    WorkflowTemplate,
)
from app.services.signing_agent import SigningAgentClient, SigningAgentError
from app.services.workflow import WorkflowService

from .conftest import auth_headers, register_and_login


def test_user_crud_flow(client: TestClient, db_session: Session) -> None:
    token, _ = register_and_login(client, "admin@example.com", "password123")
    headers = auth_headers(token)

    areas_resp = client.get(f"{settings.api_v1_str}/tenants/areas", headers=headers)
    assert areas_resp.status_code == status.HTTP_200_OK
    areas = areas_resp.json()
    assert areas

    area_resp = client.post(
        f"{settings.api_v1_str}/tenants/areas",
        json={"name": "Financeiro"},
        headers=headers,
    )
    assert area_resp.status_code == status.HTTP_201_CREATED
    area_id = UUID(area_resp.json()["id"])

    user_payload = {
        "email": "colaborador@example.com",
        "cpf": "98765432100",
        "full_name": "Colaborador",
        "password": "senha123",
        "default_area_id": str(area_id),
        "profile": UserRole.USER.value,
    }
    create_resp = client.post(f"{settings.api_v1_str}/users", json=user_payload, headers=headers)
    assert create_resp.status_code == status.HTTP_201_CREATED
    user_id = UUID(create_resp.json()["id"])

    patch_resp = client.patch(
        f"{settings.api_v1_str}/users/{user_id}",
        json={"full_name": "Colaborador Atualizado"},
        headers=headers,
    )
    assert patch_resp.status_code == status.HTTP_200_OK
    assert patch_resp.json()["full_name"] == "Colaborador Atualizado"

    delete_resp = client.delete(f"{settings.api_v1_str}/users/{user_id}", headers=headers)
    assert delete_resp.status_code == status.HTTP_204_NO_CONTENT

    db_session.expire_all()
    db_user = db_session.get(User, user_id)
    assert db_user is not None
    assert db_user.is_active is False

    audit_resp = client.get(f"{settings.api_v1_str}/audit/events", headers=headers)
    assert audit_resp.status_code == status.HTTP_200_OK
    assert audit_resp.json()


def test_document_workflow_sequential_flow(client: TestClient, db_session: Session) -> None:
    token, admin_email = register_and_login(client, "workflow@example.com", "password123")
    headers = auth_headers(token)

    areas_resp = client.get(f"{settings.api_v1_str}/tenants/areas", headers=headers)
    area_id = UUID(areas_resp.json()[0]["id"])

    doc_resp = client.post(
        f"{settings.api_v1_str}/documents",
        json={"name": "Contrato", "area_id": str(area_id)},
        headers=headers,
    )
    assert doc_resp.status_code == status.HTTP_201_CREATED
    document_id = UUID(doc_resp.json()["id"])

    version_resp = client.post(
        f"{settings.api_v1_str}/documents/{document_id}/versions",
        files={"file": ("contrato.pdf", b"conteudo", "application/pdf")},
        headers=headers,
    )
    assert version_resp.status_code == status.HTTP_201_CREATED

    party_resp = client.post(
        f"{settings.api_v1_str}/documents/{document_id}/parties",
        json={
            "full_name": "Admin Teste",
            "email": admin_email,
            "role": "signer",
            "order_index": 1,
        },
        headers=headers,
    )
    assert party_resp.status_code == status.HTTP_201_CREATED

    dispatch_resp = client.post(
        f"{settings.api_v1_str}/workflows/documents/{document_id}",
        json={"deadline_at": None},
        headers=headers,
    )
    assert dispatch_resp.status_code == status.HTTP_201_CREATED
    workflow_id = UUID(dispatch_resp.json()["id"])

    db_session.expire_all()
    step = db_session.exec(
        select(WorkflowStep).where(WorkflowStep.workflow_id == workflow_id).order_by(WorkflowStep.step_index)
    ).first()
    assert step is not None

    request_obj = db_session.exec(
        select(SignatureRequest).where(SignatureRequest.workflow_step_id == step.id)
    ).first()
    assert request_obj is not None

    workflow_service = WorkflowService(db_session)
    token_value = workflow_service.issue_signature_token(request_obj.id)
    db_session.commit()
    preview_resp = client.get(f"/public/signatures/{token_value}/preview")
    assert preview_resp.status_code == status.HTTP_200_OK
    assert preview_resp.headers.get("content-type", "").startswith("application/pdf")

    sign_resp = client.post(
        f"{settings.api_v1_str}/workflows/signatures/{request_obj.id}/actions",
        json={"action": "sign"},
        headers=headers,
    )
    assert sign_resp.status_code == status.HTTP_200_OK

    db_session.expire_all()
    updated_request = db_session.get(SignatureRequest, request_obj.id)
    assert updated_request is not None
    assert updated_request.status == SignatureRequestStatus.SIGNED

    workflow = db_session.get(WorkflowInstance, workflow_id)
    assert workflow is not None
    assert workflow.status == WorkflowStatus.COMPLETED

    document = db_session.get(Document, document_id)
    assert document is not None
    assert document.status == DocumentStatus.COMPLETED

    audit_events = db_session.exec(select(AuditLog).where(AuditLog.document_id == document_id)).all()
    assert audit_events

    verification_resp = client.get(f"/public/verification/{document_id}")
    assert verification_resp.status_code == status.HTTP_200_OK
    verification = verification_resp.json()
    assert verification["status"] == DocumentStatus.COMPLETED.value
    assert verification["download_url"].endswith(f"/public/verification/{document_id}/download")
    assert verification["version_filename"] == "contrato-assinatura-final.pdf"
    assert verification["version_size"] == len(b"conteudo")
    assert verification["signers"][0]["role"] == "signer"
    assert verification["signers"][0]["action"] == "sign"
    assert verification["signers"][0]["status"] == SignatureRequestStatus.SIGNED.value
    assert verification["workflows"][0]["steps_total"] == 1
    assert verification["workflows"][0]["steps_completed"] == 1

    html_resp = client.get(f"/public/verification/{document_id}/page")
    assert html_resp.status_code == status.HTTP_200_OK
    assert "Contrato" in html_resp.text

    download_resp = client.get(f"/public/verification/{document_id}/download")
    assert download_resp.status_code == status.HTTP_200_OK
    assert download_resp.headers["content-disposition"].startswith("attachment")
    assert download_resp.content == b"conteudo"


def test_workflow_refusal_generates_logs(client: TestClient, db_session: Session) -> None:
    token, admin_email = register_and_login(client, "refusal@example.com", "password123")
    headers = auth_headers(token)

    areas_resp = client.get(f"{settings.api_v1_str}/tenants/areas", headers=headers)
    area_id = UUID(areas_resp.json()[0]["id"])

    doc_resp = client.post(
        f"{settings.api_v1_str}/documents",
        json={"name": "Contrato Ref", "area_id": str(area_id)},
        headers=headers,
    )
    document_id = UUID(doc_resp.json()["id"])

    client.post(
        f"{settings.api_v1_str}/documents/{document_id}/versions",
        files={"file": ("contrato.pdf", b"conteudo", "application/pdf")},
        headers=headers,
    )

    client.post(
        f"{settings.api_v1_str}/documents/{document_id}/parties",
        json={
            "full_name": "Admin Teste",
            "email": admin_email,
            "role": "signer",
            "order_index": 1,
        },
        headers=headers,
    )

    dispatch_resp = client.post(
        f"{settings.api_v1_str}/workflows/documents/{document_id}",
        json={"deadline_at": None},
        headers=headers,
    )
    workflow_id = UUID(dispatch_resp.json()["id"])

    step = db_session.exec(
        select(WorkflowStep).where(WorkflowStep.workflow_id == workflow_id)
    ).first()
    request_obj = db_session.exec(
        select(SignatureRequest).where(SignatureRequest.workflow_step_id == step.id)
    ).first()

    client.post(
        f"{settings.api_v1_str}/workflows/signatures/{request_obj.id}/actions",
        json={"action": "refuse", "reason": "Recusa"},
        headers=headers,
    )

    db_session.expire_all()
    workflow = db_session.get(WorkflowInstance, workflow_id)
    document = db_session.get(Document, document_id)

    assert workflow.status == WorkflowStatus.REJECTED
    assert document.status == DocumentStatus.REJECTED

    audit_resp = client.get(f"{settings.api_v1_str}/audit/events", headers=headers)
    events = audit_resp.json()
    event_items = events["items"] if isinstance(events, dict) and "items" in events else events
    assert any(event["event_type"] == "signature_refuse" for event in event_items)


def test_public_signature_flow(client: TestClient, db_session: Session) -> None:
    token, admin_email = register_and_login(client, "public@example.com", "password123")
    headers = auth_headers(token)

    areas_resp = client.get(f"{settings.api_v1_str}/tenants/areas", headers=headers)
    area_id = UUID(areas_resp.json()[0]["id"])

    doc_resp = client.post(
        f"{settings.api_v1_str}/documents",
        json={"name": "Contrato Public", "area_id": str(area_id)},
        headers=headers,
    )
    document_id = UUID(doc_resp.json()["id"])

    client.post(
        f"{settings.api_v1_str}/documents/{document_id}/versions",
        files={"file": ("contrato.pdf", b"conteudo", "application/pdf")},
        headers=headers,
    )

    client.post(
        f"{settings.api_v1_str}/documents/{document_id}/parties",
        json={
            "full_name": "Admin Teste",
            "email": admin_email,
            "role": "signer",
            "order_index": 1,
        },
        headers=headers,
    )

    dispatch_resp = client.post(
        f"{settings.api_v1_str}/workflows/documents/{document_id}",
        json={"deadline_at": None},
        headers=headers,
    )
    workflow_id = UUID(dispatch_resp.json()["id"])

    step = db_session.exec(
        select(WorkflowStep).where(WorkflowStep.workflow_id == workflow_id)
    ).first()
    request_obj = db_session.exec(
        select(SignatureRequest).where(SignatureRequest.workflow_step_id == step.id)
    ).first()

    workflow_service = WorkflowService(db_session)
    token_value = workflow_service.issue_signature_token(request_obj.id)
    db_session.commit()

    page_resp = client.get(f"/public/signatures/{token_value}/page")
    assert page_resp.status_code == status.HTTP_200_OK
    assert "Contrato Public" in page_resp.text

    public_initial = client.get(f"/public/signatures/{token_value}")
    assert public_initial.status_code == status.HTTP_200_OK
    public_payload = public_initial.json()
    assert "supports_certificate" in public_payload
    assert isinstance(public_payload["supports_certificate"], bool)
    assert "requires_certificate" in public_payload
    assert isinstance(public_payload["requires_certificate"], bool)

    party_db = db_session.exec(select(DocumentParty).where(DocumentParty.document_id == document_id)).first()
    assert party_db is not None

    form_resp = client.post(
        f"/public/signatures/{token_value}/page",
        data={"action": "sign", "reason": "", "confirm_email": party_db.email},
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert form_resp.status_code == status.HTTP_200_OK
    assert "Assinatura registrada" in form_resp.text

    public_resp = client.get(f"/public/signatures/{token_value}")
    assert public_resp.status_code == status.HTTP_404_NOT_FOUND

    verification = client.get(f"/public/verification/{document_id}").json()
    assert verification["report_url"] is not None

    report_resp = client.get(verification["report_url"])
    assert report_resp.status_code == status.HTTP_200_OK
    assert report_resp.headers["content-type"] == "application/pdf"

    db_session.expire_all()
    updated_request = db_session.get(SignatureRequest, request_obj.id)
    assert updated_request.status == SignatureRequestStatus.SIGNED
    document = db_session.get(Document, document_id)
    assert document.status == DocumentStatus.COMPLETED


def test_public_signature_with_certificate_payload(client: TestClient, db_session: Session) -> None:
    token, admin_email = register_and_login(client, "public-cert@example.com", "password123")
    headers = auth_headers(token)

    area_resp = client.get(f"{settings.api_v1_str}/tenants/areas", headers=headers)
    area_id = UUID(area_resp.json()[0]["id"])

    doc_resp = client.post(
        f"{settings.api_v1_str}/documents",
        json={"name": "Contrato Cert", "area_id": str(area_id)},
        headers=headers,
    )
    assert doc_resp.status_code == status.HTTP_201_CREATED
    document_id = UUID(doc_resp.json()["id"])

    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"

    version_resp = client.post(
        f"{settings.api_v1_str}/documents/{document_id}/versions",
        files={"file": ("contrato.pdf", pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert version_resp.status_code == status.HTTP_201_CREATED

    party_resp = client.post(
        f"{settings.api_v1_str}/documents/{document_id}/parties",
        json={
            "full_name": "Participante Certificado",
            "email": admin_email,
            "role": "signer",
            "order_index": 1,
            "signature_method": "digital",
            "cpf": "12345678901",
        },
        headers=headers,
    )
    assert party_resp.status_code == status.HTTP_201_CREATED

    dispatch_resp = client.post(
        f"{settings.api_v1_str}/workflows/documents/{document_id}",
        json={"deadline_at": None},
        headers=headers,
    )
    assert dispatch_resp.status_code == status.HTTP_201_CREATED
    workflow_id = UUID(dispatch_resp.json()["id"])

    db_session.expire_all()
    step = db_session.exec(
        select(WorkflowStep).where(WorkflowStep.workflow_id == workflow_id)
    ).first()
    assert step is not None

    request_obj = db_session.exec(
        select(SignatureRequest).where(SignatureRequest.workflow_step_id == step.id)
    ).first()
    assert request_obj is not None

    db_session.expire_all()
    workflow_service = WorkflowService(db_session)
    token_value = workflow_service.issue_signature_token(request_obj.id)
    db_session.commit()

    signed_pdf_bytes = b"assinatura-digital"
    signed_pdf_b64 = base64.b64encode(signed_pdf_bytes).decode("ascii")

    payload = {
        "action": "sign",
        "typed_name": "Participante Certificado",
        "consent": True,
        "confirm_email": admin_email,
        "signed_pdf": signed_pdf_b64,
        "signed_pdf_name": "assinatura-final.pdf",
        "signed_pdf_mime": "application/pdf",
        "certificate_subject": "CN=Participante Certificado, SERIALNUMBER=CPF 123.456.789-01",
        "certificate_issuer": "Autoridade Virtual",
        "certificate_serial": "123456789",
        "certificate_thumbprint": "ABCDEF123",
        "signature_protocol": "PROTO-999",
        "signature_type": "ICP-Brasil",
        "signature_authentication": "Certificado digital",
    }

    public_resp = client.post(f"/public/signatures/{token_value}", json=payload)
    assert public_resp.status_code == status.HTTP_200_OK
    body = public_resp.json()
    assert body["can_sign"] is False
    assert body["supports_certificate"] is True

    db_session.expire_all()


def test_public_signature_certificate_cpf_mismatch(client: TestClient, db_session: Session) -> None:
    token, admin_email = register_and_login(client, "public-cert-mismatch@example.com", "password123")
    headers = auth_headers(token)

    area_resp = client.get(f"{settings.api_v1_str}/tenants/areas", headers=headers)
    area_id = UUID(area_resp.json()[0]["id"])

    doc_resp = client.post(
        f"{settings.api_v1_str}/documents",
        json={"name": "Contrato Cert Mismatch", "area_id": str(area_id)},
        headers=headers,
    )
    assert doc_resp.status_code == status.HTTP_201_CREATED
    document_id = UUID(doc_resp.json()["id"])

    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
    version_resp = client.post(
        f"{settings.api_v1_str}/documents/{document_id}/versions",
        files={"file": ("contrato.pdf", pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert version_resp.status_code == status.HTTP_201_CREATED

    party_resp = client.post(
        f"{settings.api_v1_str}/documents/{document_id}/parties",
        json={
            "full_name": "Participante Certificado",
            "email": admin_email,
            "role": "signer",
            "order_index": 1,
            "signature_method": "digital",
            "cpf": "98765432100",
        },
        headers=headers,
    )
    assert party_resp.status_code == status.HTTP_201_CREATED

    dispatch_resp = client.post(
        f"{settings.api_v1_str}/workflows/documents/{document_id}",
        json={"deadline_at": None},
        headers=headers,
    )
    assert dispatch_resp.status_code == status.HTTP_201_CREATED
    workflow_id = UUID(dispatch_resp.json()["id"])

    db_session.expire_all()
    step = db_session.exec(
        select(WorkflowStep).where(WorkflowStep.workflow_id == workflow_id)
    ).first()
    assert step is not None

    request_obj = db_session.exec(
        select(SignatureRequest).where(SignatureRequest.workflow_step_id == step.id)
    ).first()
    assert request_obj is not None

    db_session.expire_all()
    workflow_service = WorkflowService(db_session)
    token_value = workflow_service.issue_signature_token(request_obj.id)
    db_session.commit()

    signed_pdf_bytes = b"assinatura-digital"
    signed_pdf_b64 = base64.b64encode(signed_pdf_bytes).decode("ascii")

    mismatch_payload = {
        "action": "sign",
        "typed_name": "Participante Certificado",
        "consent": True,
        "confirm_email": admin_email,
        "signed_pdf": signed_pdf_b64,
        "signed_pdf_name": "assinatura-final.pdf",
        "signed_pdf_mime": "application/pdf",
        "certificate_subject": "CN=Participante Certificado, SERIALNUMBER=CPF 123.456.789-01",
        "certificate_issuer": "Autoridade Virtual",
        "certificate_serial": "123456789",
        "certificate_thumbprint": "ABCDEF123",
        "signature_protocol": "PROTO-000",
        "signature_type": "ICP-Brasil",
        "signature_authentication": "Certificado digital",
    }

    public_resp = client.post(f"/public/signatures/{token_value}", json=mismatch_payload)
    assert public_resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "CPF do certificado digital" in public_resp.json()["detail"]
    updated_request = db_session.get(SignatureRequest, request_obj.id)
    assert updated_request is not None
    assert updated_request.status == SignatureRequestStatus.SENT

    signature_entry = db_session.exec(
        select(Signature).where(Signature.signature_request_id == request_obj.id)
    ).first()
    assert signature_entry is None

    artifact = db_session.exec(
        select(AuditArtifact)
        .where(AuditArtifact.document_id == document_id)
        .where(AuditArtifact.artifact_type == "signature_pdf")
    ).first()
    assert artifact is None


def test_admin_templates_page(client: TestClient, db_session: Session) -> None:
    token, admin_email = register_and_login(client, "admin-templ@example.com", "password123")
    headers = auth_headers(token)

    user = db_session.exec(select(User).where(User.email == admin_email)).first()
    tenant_id = user.tenant_id

    list_resp = client.get("/admin/templates", params={"tenant_id": str(tenant_id)})
    assert list_resp.status_code == status.HTTP_200_OK

    area = db_session.exec(select(Area).where(Area.tenant_id == tenant_id)).first()
    form_data = {
        "action": "create",
        "tenant_id": str(tenant_id),
        "area_id": str(area.id),
        "name": "Fluxo Teste",
        "description": "",
        "steps_json": "[{\"order\":1,\"role\":\"signer\",\"action\":\"sign\",\"execution\":\"sequential\"}]",
    }
    create_resp = client.post(
        "/admin/templates",
        data=form_data,
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert create_resp.status_code == status.HTTP_303_SEE_OTHER

    db_session.expire_all()
    template = db_session.exec(
        select(WorkflowTemplate).where(WorkflowTemplate.name == "Fluxo Teste")
    ).first()
    assert template is not None
    assert template.tenant_id == tenant_id


def test_workflow_template_crud_and_dispatch(client: TestClient, db_session: Session) -> None:
    token, admin_email = register_and_login(client, "template@example.com", "password123")
    headers = auth_headers(token)

    areas_resp = client.get(f"{settings.api_v1_str}/tenants/areas", headers=headers)
    area_id = UUID(areas_resp.json()[0]["id"])

    doc_resp = client.post(
        f"{settings.api_v1_str}/documents",
        json={"name": "Contrato Template", "area_id": str(area_id)},
        headers=headers,
    )
    document_id = UUID(doc_resp.json()["id"])

    client.post(
        f"{settings.api_v1_str}/documents/{document_id}/versions",
        files={"file": ("contrato.pdf", b"conteudo", "application/pdf")},
        headers=headers,
    )

    client.post(
        f"{settings.api_v1_str}/documents/{document_id}/parties",
        json={
            "full_name": "Admin Teste",
            "email": admin_email,
            "role": "signer",
            "order_index": 1,
        },
        headers=headers,
    )

    approver_email = "aprovador@example.com"
    client.post(
        f"{settings.api_v1_str}/documents/{document_id}/parties",
        json={
            "full_name": "Aprovador Teste",
            "email": approver_email,
            "role": "approver",
            "order_index": 2,
        },
        headers=headers,
    )

    template_payload = {
        "area_id": str(area_id),
        "name": "Fluxo Inicial",
        "description": "Fluxo com aprovador",
        "steps": [
            {"order": 1, "role": "signer", "action": "sign", "execution": "sequential"},
            {"order": 2, "role": "approver", "action": "approve", "execution": "sequential", "deadline_hours": 24},
        ],
    }
    template_resp = client.post(
        f"{settings.api_v1_str}/workflows/templates",
        json=template_payload,
        headers=headers,
    )
    assert template_resp.status_code == status.HTTP_201_CREATED
    template = template_resp.json()
    template_id = UUID(template["id"])
    assert len(template["steps"]) == 2

    get_resp = client.get(f"{settings.api_v1_str}/workflows/templates/{template_id}", headers=headers)
    assert get_resp.status_code == status.HTTP_200_OK
    assert get_resp.json()["name"] == "Fluxo Inicial"

    update_resp = client.put(
        f"{settings.api_v1_str}/workflows/templates/{template_id}",
        json={
            "name": "Fluxo Revisado",
            "steps": [
                {"order": 1, "role": "approver", "action": "approve", "execution": "sequential"},
                {"order": 2, "role": "signer", "action": "sign", "execution": "sequential"},
            ],
        },
        headers=headers,
    )
    assert update_resp.status_code == status.HTTP_200_OK
    assert update_resp.json()["name"] == "Fluxo Revisado"
    assert update_resp.json()["steps"][0]["role"] == "approver"

    duplicate_resp = client.post(
        f"{settings.api_v1_str}/workflows/templates/{template_id}/duplicate",
        json={"name": "Fluxo Copia"},
        headers=headers,
    )
    assert duplicate_resp.status_code == status.HTTP_201_CREATED
    duplicate_id = UUID(duplicate_resp.json()["id"])

    delete_resp = client.delete(
        f"{settings.api_v1_str}/workflows/templates/{template_id}",
        headers=headers,
    )
    assert delete_resp.status_code == status.HTTP_204_NO_CONTENT

    list_inactive_resp = client.get(
        f"{settings.api_v1_str}/workflows/templates",
        params={"include_inactive": "true"},
        headers=headers,
    )
    assert list_inactive_resp.status_code == status.HTTP_200_OK
    templates = list_inactive_resp.json()
    assert any(item["id"] == str(template_id) and item["is_active"] is False for item in templates)

    dispatch_resp = client.post(
        f"{settings.api_v1_str}/workflows/documents/{document_id}",
        json={"template_id": str(duplicate_id)},
        headers=headers,
    )
    assert dispatch_resp.status_code == status.HTTP_201_CREATED
    workflow_id = UUID(dispatch_resp.json()["id"])

    steps = db_session.exec(
        select(WorkflowStep)
        .where(WorkflowStep.workflow_id == workflow_id)
        .order_by(WorkflowStep.step_index)
    ).all()
    assert len(steps) == 2
    first_party = db_session.get(DocumentParty, steps[0].party_id)
    second_party = db_session.get(DocumentParty, steps[1].party_id)

    assert first_party.role == "approver"
    assert steps[0].action == "approve"
    assert second_party.role == "signer"
    assert steps[1].action == "sign"
    assert steps[1].deadline_at is None
    assert steps[0].deadline_at is None

    # Duplicate still active
    dup_template = client.get(
        f"{settings.api_v1_str}/workflows/templates/{duplicate_id}",
        headers=headers,
    )
    assert dup_template.status_code == status.HTTP_200_OK
    assert dup_template.json()["is_active"] is True


def test_document_party_email_validation(client: TestClient) -> None:
    token, _ = register_and_login(client, "validation@example.com", "password123")
    headers = auth_headers(token)

    areas_resp = client.get(f"{settings.api_v1_str}/tenants/areas", headers=headers)
    assert areas_resp.status_code == status.HTTP_200_OK
    area_id = UUID(areas_resp.json()[0]["id"])

    doc_resp = client.post(
        f"{settings.api_v1_str}/documents",
        json={"name": "Contrato Email", "area_id": str(area_id)},
        headers=headers,
    )
    assert doc_resp.status_code == status.HTTP_201_CREATED
    document_id = UUID(doc_resp.json()["id"])

    invalid_resp = client.post(
        f"{settings.api_v1_str}/documents/{document_id}/parties",
        json={
            "full_name": "Teste Invalido",
            "email": "email-invalido",
            "role": "signer",
            "order_index": 1,
        },
        headers=headers,
    )
    assert invalid_resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_signing_agent_attempts_retry_flow(
    monkeypatch, client: TestClient, db_session: Session
) -> None:
    token, admin_email = register_and_login(client, "agent@example.com", "password123")
    headers = auth_headers(token)

    areas_resp = client.get(f"{settings.api_v1_str}/tenants/areas", headers=headers)
    assert areas_resp.status_code == status.HTTP_200_OK
    area_id = UUID(areas_resp.json()[0]["id"])

    doc_resp = client.post(
        f"{settings.api_v1_str}/documents",
        json={"name": "Contrato Agente", "area_id": str(area_id)},
        headers=headers,
    )
    assert doc_resp.status_code == status.HTTP_201_CREATED
    document_id = UUID(doc_resp.json()["id"])

    version_resp = client.post(
        f"{settings.api_v1_str}/documents/{document_id}/versions",
        files={"file": ("contrato.pdf", b"conteudo", "application/pdf")},
        headers=headers,
    )
    assert version_resp.status_code == status.HTTP_201_CREATED
    version_id = UUID(version_resp.json()["id"])

    latest_before_attempt = client.get(
        f"{settings.api_v1_str}/documents/{document_id}/versions/{version_id}/sign-agent/attempts/latest",
        headers=headers,
    )
    assert latest_before_attempt.status_code == status.HTTP_200_OK
    assert latest_before_attempt.json() is None

    def failing_sign_pdf(self, payload):
        raise SigningAgentError("PIN incorreto", details={"code": "PIN_INVALID"}, status_code=400)

    monkeypatch.setattr(SigningAgentClient, "sign_pdf", failing_sign_pdf)

    sign_url = (
        f"{settings.api_v1_str}/documents/{document_id}/versions/{version_id}/sign-agent"
    )
    fail_resp = client.post(sign_url, json={"protocol": "PROTO-INIT"}, headers=headers)
    assert fail_resp.status_code == status.HTTP_400_BAD_REQUEST
    fail_payload = fail_resp.json()["detail"]
    attempt_id = fail_payload["attempt_id"]
    assert fail_payload["agent_details"]["code"] == "PIN_INVALID"

    latest_resp = client.get(
        f"{settings.api_v1_str}/documents/{document_id}/versions/{version_id}/sign-agent/attempts/latest",
        headers=headers,
    )
    assert latest_resp.status_code == status.HTTP_200_OK
    latest_data = latest_resp.json()
    assert latest_data["status"] == SigningAgentAttemptStatus.ERROR.value
    assert latest_data["payload"]["protocol"] == "PROTO-INIT"

    def success_sign_pdf(self, payload):
        return {
            "pdf": base64.b64encode(b"signed-pdf").decode("ascii"),
            "protocol": "PROTO-SUCCESS",
            "signatureType": "Assinatura digital",
            "authentication": "Certificado A3",
        }

    monkeypatch.setattr(SigningAgentClient, "sign_pdf", success_sign_pdf)

    retry_resp = client.post(
        f"{settings.api_v1_str}/documents/{document_id}/versions/{version_id}/sign-agent/retry",
        headers=headers,
    )
    assert retry_resp.status_code == status.HTTP_200_OK
    retry_data = retry_resp.json()
    assert retry_data["protocol"] == "PROTO-SUCCESS"

    latest_retry = client.get(
        f"{settings.api_v1_str}/documents/{document_id}/versions/{version_id}/sign-agent/attempts/latest",
        headers=headers,
    )
    assert latest_retry.status_code == status.HTTP_200_OK
    latest_retry_data = latest_retry.json()
    assert latest_retry_data["status"] == SigningAgentAttemptStatus.SUCCESS.value
    assert latest_retry_data["protocol"] == "PROTO-SUCCESS"

    db_session.expire_all()
    attempts = db_session.exec(
        select(SigningAgentAttempt)
        .where(SigningAgentAttempt.document_id == document_id)
        .order_by(SigningAgentAttempt.created_at)
    ).all()
    assert len(attempts) >= 2
    assert attempts[-2].status == SigningAgentAttemptStatus.ERROR
    assert attempts[-1].status == SigningAgentAttemptStatus.SUCCESS
    assert (attempts[-1].payload or {}).get("protocol") == "PROTO-INIT"
    assert attempts[-1].protocol == "PROTO-SUCCESS"
