from typing import List, Optional, TYPE_CHECKING
from uuid import UUID

from sqlmodel import Field, Relationship

from app.models.base import TimestampedModel, UUIDModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.document import Document
    from app.models.user import User


class Tenant(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "tenants"

    name: str = Field(index=True)
    slug: str = Field(unique=True, index=True)
    cnpj: str | None = Field(default=None, max_length=18)
    plan_id: str | None = Field(default=None)
    balance_cents: int = Field(default=0)
    is_active: bool = Field(default=True)
    # Multi-tenant avançado
    theme: str | None = Field(default=None, max_length=32)  # Ex: "light", "dark", "custom"
    max_users: int | None = Field(default=None)
    max_documents: int | None = Field(default=None)
    custom_logo_url: str | None = Field(default=None)

    areas: List["Area"] = Relationship(back_populates="tenant")
    users: List["User"] = Relationship(back_populates="tenant")


class Area(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "areas"

    name: str = Field(index=True)
    description: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)

    tenant_id: UUID = Field(foreign_key="tenants.id")

    tenant: "Tenant" = Relationship(back_populates="areas")
    documents: List["Document"] = Relationship(back_populates="area")
