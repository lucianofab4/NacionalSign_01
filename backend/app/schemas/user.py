from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.models.user import UserRole
from app.schemas.common import IDModel, Timestamped


class UserCreate(BaseModel):
    email: EmailStr
    cpf: str | None = None
    full_name: str
    phone_number: str | None = None
    password: str
    default_area_id: UUID | None = None
    profile: UserRole = UserRole.USER


class UserRead(IDModel, Timestamped):
    tenant_id: UUID
    default_area_id: UUID | None
    email: EmailStr
    cpf: str | None = None
    full_name: str
    phone_number: str | None
    profile: UserRole
    is_active: bool
    two_factor_enabled: bool
    last_login_at: datetime | None


class UserUpdate(BaseModel):
    full_name: str | None = None
    phone_number: str | None = None
    password: str | None = None
    two_factor_enabled: bool | None = None
    is_active: bool | None = None
    profile: UserRole | None = None
    default_area_id: UUID | None = None


class UserSettingsUpdate(BaseModel):
    full_name: str | None = None
    phone_number: str | None = None
    password: str | None = None
    two_factor_enabled: bool | None = None
    default_area_id: UUID | None = None


class UserPasswordResetResponse(BaseModel):
    user_id: UUID
    email: EmailStr
    temporary_password: str
