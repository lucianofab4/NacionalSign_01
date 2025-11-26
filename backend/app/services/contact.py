from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlmodel import Session, func, select

from app.models.contact import Contact


class ContactService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def search(self, tenant_id: UUID, query: str = "", limit: int = 10) -> list[Contact]:
        statement = select(Contact).where(Contact.tenant_id == tenant_id)
        if query:
            pattern = f"%{query.lower()}%"
            statement = statement.where(
                func.lower(Contact.full_name).like(pattern)
                | func.lower(Contact.email).like(pattern)
                | func.lower(Contact.company_name).like(pattern)
                | func.lower(Contact.phone_number).like(pattern)
            )
        statement = statement.order_by(Contact.updated_at.desc(), Contact.created_at.desc()).limit(max(limit, 1))
        return self.session.exec(statement).all()

    def upsert_from_payload(self, tenant_id: UUID, payload: dict[str, Any]) -> Contact:
        normalized = self._normalize_payload(payload)
        contact = self._find_existing(tenant_id, normalized)
        if contact:
            self._apply_updates(contact, normalized)
        else:
            contact = Contact(tenant_id=tenant_id, **normalized)
            self.session.add(contact)
        return contact

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for key in ("full_name", "email", "phone_number", "company_name"):
            value = payload.get(key)
            if isinstance(value, str):
                cleaned[key] = value.strip() or None
            elif value is not None:
                cleaned[key] = value
        for key in ("cpf", "company_tax_id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                digits = "".join(ch for ch in value if ch.isdigit())
                cleaned[key] = digits or None
            else:
                cleaned[key] = value or None
        cleaned.setdefault("full_name", None)
        return cleaned

    def _find_existing(self, tenant_id: UUID, data: dict[str, Any]) -> Contact | None:
        base = select(Contact).where(Contact.tenant_id == tenant_id)
        if data.get("email"):
            contact = self.session.exec(
                base.where(func.lower(Contact.email) == data["email"].lower())
            ).first()
            if contact:
                return contact
        if data.get("cpf"):
            contact = self.session.exec(
                base.where(Contact.cpf == data["cpf"])
            ).first()
            if contact:
                return contact
        if data.get("phone_number"):
            contact = self.session.exec(
                base.where(Contact.phone_number == data["phone_number"])
            ).first()
            if contact:
                return contact
        if data.get("full_name"):
            contact = self.session.exec(
                base.where(func.lower(Contact.full_name) == data["full_name"].lower())
            ).first()
            if contact:
                return contact
        return None

    def _apply_updates(self, contact: Contact, data: dict[str, Any]) -> None:
        for key, value in data.items():
            if value:
                setattr(contact, key, value)
