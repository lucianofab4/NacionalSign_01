from uuid import uuid4

import pytest
from sqlmodel import Session

from app.models.document import Document, DocumentParty, DocumentStatus
from app.models.tenant import Area, Tenant
from app.models.user import User
from app.schemas.document import DocumentPartyCreate, DocumentPartyUpdate
from app.services.document import DocumentService


@pytest.fixture()
def base_document(db_session: Session) -> dict:
    tenant = Tenant(name="Tenant", slug=f"tenant-{uuid4().hex[:6]}")
    area = Area(name="Area", tenant_id=tenant.id)
    user = User(
        tenant_id=tenant.id,
        email=f"user_{uuid4().hex[:6]}@example.com",
        cpf="12345678901",
        full_name="User Test",
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
    db_session.commit()
    return {"tenant": tenant, "area": area, "user": user, "document": document}


def test_add_party_validates_channel(db_session: Session, base_document: dict) -> None:
    service = DocumentService(db_session)
    document = base_document["document"]

    payload = DocumentPartyCreate(
        full_name="Signer",
        email="signer@example.com",
        role="signer",
        notification_channel="email",
    )
    party = service.add_party(document, payload)

    assert party.notification_channel == "email"

    with pytest.raises(ValueError):
        service.add_party(
            document,
            DocumentPartyCreate(
                full_name="SMS",
                role="signer",
                notification_channel="sms",
            ),
        )

    with pytest.raises(ValueError):
        service.add_party(
            document,
            DocumentPartyCreate(
                full_name="Bad",
                email="bad@example.com",
                role="signer",
                notification_channel="push",
            ),
        )


def test_update_party_changes_channel(db_session: Session, base_document: dict) -> None:
    service = DocumentService(db_session)
    document = base_document["document"]
    party = service.add_party(
        document,
        DocumentPartyCreate(full_name="Signer", email="signer@example.com", role="signer"),
    )

    payload = DocumentPartyUpdate(notification_channel="sms", phone_number="+5511999999999")
    updated = service.update_party(party, payload)

    assert updated.notification_channel == "sms"
    assert updated.phone_number == "+5511999999999"

    with pytest.raises(ValueError):
        service.update_party(party, DocumentPartyUpdate(notification_channel="push"))
