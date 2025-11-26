from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlmodel import Session, select

from app.models.audit import AuditLog, AuthLog
from app.models.document import Document, DocumentStatus
from app.models.tenant import Area, Tenant
from app.models.user import User, UserRole
from app.services.audit import AuditService


@pytest.fixture()
def sample_context(db_session: Session) -> dict:
    tenant = Tenant(name="Tenant", slug=f"tenant-{uuid4().hex[:6]}")
    area = Area(name="Area", tenant_id=tenant.id)
    user = User(
        tenant_id=tenant.id,
        email=f"user_{uuid4().hex[:6]}@example.com",
        cpf="12345678901",
        full_name="User Test",
        password_hash="hash",
        profile=UserRole.ADMIN.value,
    )
    document = Document(
        tenant_id=tenant.id,
        area_id=area.id,
        name="Contrato",
        status=DocumentStatus.DRAFT,
        created_by_id=user.id,
    )

    db_session.add_all([tenant, area, user, document])
    db_session.commit()

    return {"tenant": tenant, "area": area, "user": user, "document": document}


def test_audit_service_records_events(db_session: Session, sample_context: dict) -> None:
    service = AuditService(db_session)
    document = sample_context["document"]
    user = sample_context["user"]

    service.record_event(
        event_type="workflow_dispatched",
        actor_id=user.id,
        actor_role=user.profile,
        document_id=document.id,
        ip_address="127.0.0.1",
        user_agent="pytest",
        details={"workflow_id": "wf-1"},
    )

    stored = db_session.exec(select(AuditLog)).one()
    assert stored.document_id == document.id
    assert stored.actor_id == user.id
    assert stored.details["workflow_id"] == "wf-1"


def test_audit_service_filters_by_tenant(db_session: Session, sample_context: dict) -> None:
    service = AuditService(db_session)
    tenant = sample_context["tenant"]
    document = sample_context["document"]

    past = datetime.utcnow() - timedelta(days=1)
    service.record_event("doc_created", document_id=document.id, actor_id=None, actor_role=None)

    items, total = service.list_events(
        tenant_id=tenant.id,
        start_at=past,
        end_at=datetime.utcnow() + timedelta(minutes=1),
    )

    assert total == 1
    assert len(items) == 1
    assert items[0].event_type == "doc_created"


def test_audit_service_records_auth(db_session: Session, sample_context: dict) -> None:
    service = AuditService(db_session)
    user = sample_context["user"]

    service.record_auth(
        user_id=user.id,
        event_type="login",
        ip_address="10.0.0.1",
        user_agent="pytest",
        success=False,
    )

    stored = db_session.exec(select(AuthLog)).one()
    assert stored.user_id == user.id
    assert stored.success is False
    assert stored.ip_address == "10.0.0.1"
