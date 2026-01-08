from uuid import uuid4
import base64
import hashlib

import pytest
from sqlmodel import Session, select

from app.models.audit import AuditLog
from app.models.document import Document, DocumentParty, DocumentStatus, DocumentField, DocumentVersion, AuditArtifact
from app.models.tenant import Area, Tenant
from app.models.user import User
from app.models.workflow import Signature, SignatureRequest, WorkflowStep
from app.schemas.workflow import SignatureAction, WorkflowDispatch, WorkflowStepConfig, WorkflowTemplateCreate
from app.services.notification import NotificationService
from app.services.storage import get_storage, normalize_storage_path
from app.services.workflow import WorkflowService


@pytest.fixture()
def workflow_context(db_session: Session) -> dict:
    tenant = Tenant(name="Tenant", slug=f"tenant-{uuid4().hex[:6]}")
    area = Area(name="Area", tenant_id=tenant.id)
    user = User(
        tenant_id=tenant.id,
        email=f"owner_{uuid4().hex[:6]}@example.com",
        cpf="10987654321",
        full_name="Owner",
        password_hash="hash",
    )
    document = Document(
        tenant_id=tenant.id,
        area_id=area.id,
        name="Contrato",
        status=DocumentStatus.DRAFT,
        created_by_id=user.id,
    )

    db_session.add_all([tenant, area, user, document])
    db_session.flush()

    party_signer = DocumentParty(
        document_id=document.id,
        full_name="Signer",
        email="signer@example.com",
        role="signer",
        order_index=1,
    )
    db_session.add(party_signer)
    db_session.commit()

    return {
        "tenant": tenant,
        "area": area,
        "user": user,
        "document": document,
        "party": party_signer,
    }


def test_workflow_template_duplicate_order_validation(db_session: Session, workflow_context: dict) -> None:
    service = WorkflowService(db_session, notification_service=NotificationService(session=db_session))
    tenant = workflow_context["tenant"]
    area = workflow_context["area"]

    payload = WorkflowTemplateCreate(
        area_id=area.id,
        name="Fluxo",
        description=None,
        steps=[
            WorkflowStepConfig(order=1, role="signer"),
            WorkflowStepConfig(order=1, role="approver"),
        ],
    )

    with pytest.raises(ValueError, match="orders must be unique"):
        service.create_template(tenant.id, area.id, payload)


def test_workflow_dispatch_missing_role_raises(db_session: Session, workflow_context: dict) -> None:
    service = WorkflowService(db_session, notification_service=NotificationService(session=db_session))
    tenant = workflow_context["tenant"]
    area = workflow_context["area"]
    document = workflow_context["document"]

    # template requires signer and approver, but only signer exists
    payload = WorkflowTemplateCreate(
        area_id=area.id,
        name="Fluxo",
        description=None,
        steps=[
            WorkflowStepConfig(order=1, role="signer"),
            WorkflowStepConfig(order=2, role="approver"),
        ],
    )

    template = service.create_template(tenant.id, area.id, payload)

    dispatch_payload = WorkflowDispatch(template_id=template.id)

    with pytest.raises(ValueError, match="requires party with role 'approver'"):
        service.dispatch_workflow(tenant.id, document.id, dispatch_payload)


def test_dispatch_requires_contact_validation(db_session: Session, workflow_context: dict) -> None:
    service = WorkflowService(db_session, notification_service=NotificationService(session=db_session))
    tenant = workflow_context["tenant"]
    document = workflow_context["document"]
    party = workflow_context["party"]

    party.notification_channel = "sms"
    party.phone_number = None
    db_session.add(party)
    db_session.commit()

    with pytest.raises(ValueError, match="Contatos pendentes"):
        service.dispatch_workflow(tenant.id, document.id, WorkflowDispatch())

    party.phone_number = "+55 11 99999-9999"
    db_session.add(party)
    db_session.commit()

    workflow = service.dispatch_workflow(tenant.id, document.id, WorkflowDispatch())
    step = db_session.exec(select(WorkflowStep).where(WorkflowStep.workflow_id == workflow.id)).first()
    assert step is not None
    request = db_session.exec(select(SignatureRequest).where(SignatureRequest.workflow_step_id == step.id)).first()
    assert request is not None
    assert request.token_channel == "sms"


def test_signature_action_captures_evidence(db_session: Session, workflow_context: dict) -> None:
    service = WorkflowService(db_session, notification_service=NotificationService(session=db_session))
    tenant = workflow_context["tenant"]
    document = workflow_context["document"]
    party = workflow_context["party"]
    user = workflow_context["user"]

    storage = get_storage()
    original_pdf = b"%PDF-1.1\n%%EOF"
    storage_path = storage.save_bytes(
        root=f"documents/{document.tenant_id}/{document.id}",
        name="original.pdf",
        data=original_pdf,
    )
    storage_path = normalize_storage_path(storage_path)

    version = DocumentVersion(
        document_id=document.id,
        storage_path=storage_path,
        original_filename="contrato.pdf",
        mime_type="application/pdf",
        size_bytes=len(original_pdf),
        sha256=hashlib.sha256(original_pdf).hexdigest(),
        uploaded_by_id=user.id,
    )
    db_session.add(version)
    db_session.commit()

    document.current_version_id = version.id
    db_session.add(document)
    db_session.commit()

    typed_field = DocumentField(
        document_id=document.id,
        version_id=version.id,
        role=party.role,
        field_type="typed_name",
        page=1,
        x=0.15,
        y=0.20,
        width=0.25,
        height=0.05,
        required=True,
    )
    image_field = DocumentField(
        document_id=document.id,
        version_id=version.id,
        role=party.role,
        field_type="signature_image",
        page=1,
        x=0.55,
        y=0.20,
        width=0.25,
        height=0.05,
        required=True,
    )
    db_session.add_all([typed_field, image_field])
    db_session.commit()

    workflow = service.dispatch_workflow(tenant.id, document.id, WorkflowDispatch())

    request = db_session.exec(select(SignatureRequest)).first()
    assert request is not None

    typed_name = "Maria Silva"
    image_bytes = b"fake-image-bytes"
    action = SignatureAction(
        action="sign",
        reason="ok",
        typed_name=typed_name,
        signature_image=base64.b64encode(image_bytes).decode("ascii"),
        signature_image_mime="image/png",
        signature_image_name="assinatura.png",
        consent=True,
        consent_text="Autorizo o uso da imagem para assinatura.",
        consent_version="v1",
    )

    service.record_signature_action(
        tenant_id=tenant.id,
        request_id=request.id,
        payload=action,
        ip="127.0.0.1",
        user_agent="pytest",
    )

    signature_entry = db_session.exec(
        select(Signature).where(Signature.signature_request_id == request.id)
    ).first()
    assert signature_entry is not None
    assert signature_entry.typed_name == typed_name
    assert signature_entry.typed_name_hash == hashlib.sha256(typed_name.encode("utf-8")).hexdigest()
    assert signature_entry.evidence_image_artifact_id is not None
    assert signature_entry.consent_given is True
    assert signature_entry.evidence_options is not None
    assert signature_entry.evidence_options.get("typed_name") is True
    assert signature_entry.evidence_options.get("signature_image") is True

    artifact = db_session.get(AuditArtifact, signature_entry.evidence_image_artifact_id)
    assert artifact is not None
    assert artifact.sha256 == hashlib.sha256(image_bytes).hexdigest()

    evidence_log = db_session.exec(
        select(AuditLog)
        .where(AuditLog.event_type == "signature_evidence_captured")
        .where(AuditLog.document_id == document.id)
    ).first()
    assert evidence_log is not None
    assert evidence_log.details.get("typed_name") == typed_name
    assert evidence_log.details.get("image_artifact_id") == str(artifact.id)
