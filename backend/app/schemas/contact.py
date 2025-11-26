from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ContactBase(BaseModel):
    full_name: str = Field(min_length=1)
    email: str | None = None
    cpf: str | None = None
    phone_number: str | None = None
    company_name: str | None = None
    company_tax_id: str | None = None


class ContactCreate(ContactBase):
    tenant_id: UUID


class ContactRead(ContactBase):
    id: UUID
    tenant_id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class ContactUpdate(ContactBase):
    full_name: str | None = None
