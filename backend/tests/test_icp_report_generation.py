from __future__ import annotations

from pathlib import Path
from uuid import uuid4
import base64
import hashlib

import pytest
from sqlmodel import Session, select

from app.models.audit import AuditLog
from app.models.document import AuditArtifact, Document, DocumentParty, DocumentStatus, DocumentField, DocumentVersion
from app.models.tenant import Area, Tenant
from app.models.user import User
from app.models.workflow import Signature, SignatureRequest, WorkflowStatus
from app.schemas.workflow import SignatureAction, WorkflowDispatch
from app.services import document as document_module
from app.services import report as report_module
from app.services.notification import NotificationService
from app.services.storage import get_storage, normalize_storage_path
from app.services.workflow import WorkflowService


class DummyNotification(NotificationService):
    def __init__(self) -> None:
        super().__init__(audit_service=None, email_config=None, public_base_url=None, sms_config=None)
        self.sent_signature_requests: list[dict] = []
        self.sent_completed: list[dict] = []

    # Bypass real sending and templates for unit tests
    def notify_signature_request(self, request, party, document, token: str | None = None, step=None) -> bool:  # type: ignore[override]
        self.sent_signature_requests.append({
            "party_email": getattr(party, "email", None),
            "document_id": str(document.id),
            "token_present": bool(token),
        })
        return True

    def notify_workflow_completed(self, *, document, parties, attachments=None, extra_recipients=None) -> None:  # type: ignore[override]
        recipients = [getattr(p, "email", None) for p in parties if getattr(p, "email", None)]
        for email in extra_recipients or []:
            recipients.append(email)
        self.sent_completed.append({
            "recipients": recipients,
            "attachments": [str(a) for a in (attachments or [])],
        })


@pytest.fixture()
def storage_patch(tmp_path, monkeypatch):
    base = tmp_path / "storage"
    base.mkdir(parents=True, exist_ok=True)
    # Patch both modules that cache BASE_STORAGE at import time
    monkeypatch.setattr(document_module, "BASE_STORAGE", base, raising=True)
    monkeypatch.setattr(report_module, "BASE_STORAGE", base, raising=True)
    return base


def _seed_minimal_doc(db: Session) -> tuple[Tenant, Area, User, Document, DocumentParty]:
    tenant = Tenant(name="Tenant", slug=f"tenant-{uuid4().hex[:6]}")
    area = Area(name="Area", tenant_id=tenant.id)
    owner = User(
        tenant_id=tenant.id,
        email=f"owner_{uuid4().hex[:6]}@example.com",
        cpf="10987654321",
        full_name="Owner",
        password_hash="hash",
    )
    doc = Document(
        tenant_id=tenant.id,
        area_id=area.id,
        name="Contrato",
        status=DocumentStatus.DRAFT,
        created_by_id=owner.id,
    )
    db.add_all([tenant, area, owner, doc])
    db.flush()

    signer = DocumentParty(
        document_id=doc.id,
        full_name="Signer",
        email="signer@example.com",
        role="signer",
        order_index=1,
    )
    db.add(signer)
    db.commit()
    return tenant, area, owner, doc, signer


def test_final_report_generated_with_timestamp_and_email(db_session: Session, storage_patch) -> None:
    tenant, _area, owner, document, signer = _seed_minimal_doc(db_session)

    # Create a valid minimal PDF using reportlab
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.drawString(100, 750, 'Contrato de Teste para Assinatura Digital')
    c.save()
    buffer.seek(0)
    original_pdf = buffer.getvalue()

    storage = get_storage()
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
        uploaded_by_id=owner.id,
    )
    db_session.add(version)
    db_session.commit()

    document.current_version_id = version.id
    db_session.add(document)
    db_session.commit()

    typed_field = DocumentField(
        document_id=document.id,
        version_id=version.id,
        role=signer.role,
        field_type="typed_name",
        page=1,
        x=0.12,
        y=0.18,
        width=0.28,
        height=0.05,
        required=True,
    )
    image_field = DocumentField(
        document_id=document.id,
        version_id=version.id,
        role=signer.role,
        field_type="signature_image",
        page=1,
        x=0.55,
        y=0.18,
        width=0.28,
        height=0.05,
        required=True,
    )
    db_session.add_all([typed_field, image_field])
    db_session.commit()

    notifier = DummyNotification()
    service = WorkflowService(db_session, notification_service=notifier)

    workflow = service.dispatch_workflow(tenant.id, document.id, WorkflowDispatch())

    # Obtain the pending request
    request = db_session.exec(select(SignatureRequest)).first()
    assert request is not None

    # Complete the signature
    service.record_signature_action(
        tenant.id,
        request.id,
        SignatureAction(
            action="sign",
            reason="ok",
            typed_name="Maria Silva",
            signature_image=base64.b64encode(b"sample-image").decode("ascii"),
            signature_image_mime="image/png",
            signature_image_name="assinatura.png",
            consent=True,
            consent_text="Autorizo o uso da imagem para assinatura.",
            consent_version="v1",
        ),
        ip="127.0.0.1",
        user_agent="pytest",
    )

    db_session.refresh(workflow)
    db_session.refresh(document)
    request = db_session.get(SignatureRequest, request.id)
    assert request is not None
    signature_entry = db_session.exec(
        select(Signature).where(Signature.signature_request_id == request.id)
    ).first()
    assert signature_entry is not None
    assert signature_entry.typed_name == "Maria Silva"

    assert workflow.status == WorkflowStatus.COMPLETED
    assert document.status == DocumentStatus.COMPLETED

    # Artifacts were created
    artifacts = db_session.exec(select(AuditArtifact).where(AuditArtifact.document_id == document.id)).all()
    kinds = {a.artifact_type for a in artifacts}
    assert "final_report" in kinds
    # Timestamp artifact is present when timestamp was requested (default behavior)
    assert "final_report_timestamp" in kinds

    report_artifact = next(a for a in artifacts if a.artifact_type == "final_report")
    report_path = Path(report_artifact.storage_path)
    if not report_path.is_absolute():
        report_path = storage_patch / report_path
    pdf_bytes = report_path.read_bytes()
    pdf_text = pdf_bytes.decode("latin-1", errors="ignore")
    assert "Dados fornecidos pelo" in pdf_text
    assert "Maria Silva" in pdf_text

    image_artifact = next((a for a in artifacts if a.artifact_type == "signature_image"), None)
    assert image_artifact is not None

    # Files exist on disk
    for a in artifacts:
        path = Path(a.storage_path)
        if not path.is_absolute():
            path = storage_patch / path
        assert path.exists(), f"missing artifact file: {path}"
        assert path.stat().st_size > 0

    # ICP warnings should be logged when signer is not configured (dev fallback)
    warnings = db_session.exec(
        select(AuditLog).where(
            (AuditLog.document_id == document.id) & (AuditLog.event_type == "icp_warning")
        )
    ).all()
    assert len(warnings) >= 1

    # Completion email was "sent" via notifier with attachments
    assert notifier.sent_completed, "no completion email recorded"
    sent = notifier.sent_completed[-1]
    assert "signer@example.com" in sent["recipients"]
    # Creator email is best-effort; include if relationship resolves
    # At least one attachment (the PDF) should be present
    assert any(name.endswith("relatorio-final.pdf") for name in sent["attachments"])  # type: ignore[index]
