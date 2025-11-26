from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import IDModel, Timestamped


class TenantCreate(BaseModel):
    name: str
    slug: str
    cnpj: str | None = None
    theme: str | None = None
    max_users: int | None = None
    max_documents: int | None = None
    custom_logo_url: str | None = None


class TenantRead(IDModel, Timestamped):
    name: str
    slug: str
    cnpj: str | None = None
    plan_id: str | None = None
    balance_cents: int
    is_active: bool
    theme: str | None = None
    max_users: int | None = None
    max_documents: int | None = None
    custom_logo_url: str | None = None


class AreaCreate(BaseModel):
    name: str
    description: str | None = None


class AreaUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class AreaRead(IDModel, Timestamped):
    tenant_id: UUID
    name: str
    description: str | None = None
    is_active: bool