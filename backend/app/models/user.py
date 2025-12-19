from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from sqlmodel import Field, Relationship

from app.models.base import TimestampedModel, UUIDModel
from app.models.tenant import Area, Tenant


class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    OWNER = "owner"
    ADMIN = "admin"
    AREA_MANAGER = "area_manager"
    USER = "user"
    PROCURATOR = "procurator"


class User(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "users"

    tenant_id: UUID = Field(foreign_key="tenants.id", index=True)
    default_area_id: UUID | None = Field(default=None, foreign_key="areas.id")

    email: str = Field(index=True, unique=True)
    cpf: str = Field(index=True)
    full_name: str
    phone_number: str | None = Field(default=None, max_length=32)

    password_hash: str
    profile: str = Field(default=UserRole.USER.value)
    is_active: bool = Field(default=True)
    two_factor_enabled: bool = Field(default=False)
    two_factor_secret: str | None = Field(default=None, max_length=64)
    last_login_at: datetime | None = Field(default=None)
    must_change_password: bool = Field(default=False)

    tenant: Tenant = Relationship(back_populates="users")
    default_area: Optional[Area] = Relationship()
