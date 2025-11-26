from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, ValidationInfo, field_validator

from app.schemas.common import IDModel, Timestamped


class CustomerBase(BaseModel):
    corporate_name: str
    trade_name: str | None = None
    cnpj: str
    responsible_name: str
    responsible_email: EmailStr | None = None
    responsible_phone: str | None = None
    plan_id: UUID | None = None
    document_quota: int | None = None
    is_active: bool = True

    @field_validator("cnpj")
    @classmethod
    def normalize_cnpj(cls, value: str) -> str:
        digits = ''.join(filter(str.isdigit, value or ""))
        if len(digits) not in (14, 0):
            raise ValueError("CNPJ must have 14 digits")
        return digits


class CustomerCreate(CustomerBase):
    document_quota: int | None = None

    @field_validator("document_quota")
    @classmethod
    def validate_plan_or_quota(cls, quota: Optional[int], info: ValidationInfo) -> Optional[int]:
        plan_id = info.data.get("plan_id")  # type: ignore[arg-type]
        if plan_id is None and quota is None:
            raise ValueError("Provide either a plan_id or a document_quota")
        return quota


class CustomerUpdate(BaseModel):
    corporate_name: str | None = None
    trade_name: str | None = None
    cnpj: str | None = None
    responsible_name: str | None = None
    responsible_email: EmailStr | None = None
    responsible_phone: str | None = None
    plan_id: UUID | None = None
    document_quota: int | None = None
    documents_used: int | None = None
    tenant_id: UUID | None = None
    is_active: bool | None = None

    @field_validator("cnpj")
    @classmethod
    def normalize_update_cnpj(cls, value: str | None) -> str | None:
        if value is None:
            return value
        digits = ''.join(filter(str.isdigit, value))
        if len(digits) != 14:
            raise ValueError("CNPJ must have 14 digits")
        return digits


class CustomerRead(IDModel, Timestamped):
    corporate_name: str
    trade_name: str | None = None
    cnpj: str
    responsible_name: str
    responsible_email: str | None = None
    responsible_phone: str | None = None
    plan_id: UUID | None = None
    document_quota: int | None = None
    documents_used: int
    tenant_id: UUID | None = None
    activation_token: str | None = None
    contract_file_name: str | None = None
    contract_uploaded_at: datetime | None = None
    contract_download_url: str | None = None
    is_active: bool


class CustomerActivationLink(BaseModel):
    activation_token: str
    activation_url: str


class CustomerActivationStatus(BaseModel):
    corporate_name: str
    trade_name: str | None = None
    responsible_name: str
    responsible_email: EmailStr | None = None
    plan_id: UUID | None = None
    document_quota: int | None = None
    activated: bool = False
    tenant_id: UUID | None = None


class CustomerActivationComplete(BaseModel):
    admin_full_name: str | None = None
    admin_email: EmailStr | None = None
    password: str
    confirm_password: str

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, value: str, info: ValidationInfo) -> str:
        password = info.data.get("password")
        if password != value:
            raise ValueError("Passwords do not match")
        return value


class CustomerActivationCompleteResponse(BaseModel):
    tenant_id: UUID
    user_id: UUID
    login_url: str
