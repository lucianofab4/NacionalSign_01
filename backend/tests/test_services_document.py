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


def test_add_party_requires_cpf_for_digital_signature(db_session: Session, base_document: dict) -> None:
    service = DocumentService(db_session)
    document = base_document["document"]

    with pytest.raises(ValueError):
        service.add_party(
            document,
            DocumentPartyCreate(
                full_name="Digital Signer",
                email="digital@example.com",
                role="signer",
                signature_method="digital",
            ),
        )

    party = service.add_party(
        document,
        DocumentPartyCreate(
            full_name="Com CPF",
            email="valid@example.com",
            role="signer",
            signature_method="digital",
            cpf="123.456.789-01",
        ),
    )
    assert party.cpf == "12345678901"


def test_update_party_to_digital_requires_cpf(db_session: Session, base_document: dict) -> None:
    service = DocumentService(db_session)
    document = base_document["document"]
    party = service.add_party(
        document,
        DocumentPartyCreate(
            full_name="Signer",
            email="signer@example.com",
            role="signer",
            signature_method="electronic",
        ),
    )

    with pytest.raises(ValueError):
        service.update_party(party, DocumentPartyUpdate(signature_method="digital"))

    updated = service.update_party(
        party,
        DocumentPartyUpdate(signature_method="digital", cpf="987.654.321-00"),
    )
    assert updated.signature_method == "digital"
    assert updated.cpf == "98765432100"

    with pytest.raises(ValueError):
        service.update_party(updated, DocumentPartyUpdate(cpf=None))


def test_add_party_rejects_duplicate_roles(db_session: Session, base_document: dict) -> None:
    service = DocumentService(db_session)
    document = base_document["document"]

    service.add_party(
        document,
        DocumentPartyCreate(
            full_name="CEO 1",
            email="ceo1@example.com",
            role="ceo",
        ),
    )

    with pytest.raises(ValueError):
        service.add_party(
            document,
            DocumentPartyCreate(
                full_name="CEO 2",
                email="ceo2@example.com",
                role="ceo",
            ),
        )


def test_update_party_rejects_duplicate_roles(db_session: Session, base_document: dict) -> None:
    service = DocumentService(db_session)
    document = base_document["document"]
    first = service.add_party(
        document,
        DocumentPartyCreate(full_name="CEO", email="ceo@example.com", role="ceo"),
    )
    second = service.add_party(
        document,
        DocumentPartyCreate(full_name="CFO", email="cfo@example.com", role="cfo"),
    )

    with pytest.raises(ValueError):
        service.update_party(second, DocumentPartyUpdate(role=first.role))
