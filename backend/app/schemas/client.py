from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    contact_email: EmailStr | None = None
    contact_phone: str | None = None
    notes: str | None = None


class ClientRead(BaseModel):
    id: UUID
    name: str
    portal_url: str | None = None
    contact_email: EmailStr | None = None
    contact_phone: str | None = None

    model_config = ConfigDict(from_attributes=True)
