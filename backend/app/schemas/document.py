from datetime import datetime
from uuid import UUID
from typing import Optional, List

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.document import DocumentStatus
from app.schemas.common import IDModel, Timestamped


_VALID_SIGNATURE_FLOW_MODES = {"SEQUENTIAL", "PARALLEL"}


def _normalize_signature_flow_mode(value: str | None) -> str:
    if value is None:
        return "SEQUENTIAL"
    normalized = value.strip().upper()
    if normalized not in _VALID_SIGNATURE_FLOW_MODES:
        raise ValueError("signature_flow_mode deve ser 'sequential' ou 'parallel'.")
    return normalized


# -------------------------------------------------------------------------
# Document schemas
# -------------------------------------------------------------------------

class DocumentCreate(BaseModel):
    name: str
    area_id: UUID
    signature_flow_mode: str = Field(default="SEQUENTIAL")

    @field_validator("signature_flow_mode", mode="before")
    @classmethod
    def validate_flow_mode(cls, value: str | None) -> str:
        return _normalize_signature_flow_mode(value)


class DocumentRead(IDModel, Timestamped):
    tenant_id: UUID
    area_id: UUID
    name: str
    status: DocumentStatus
    last_active_status: DocumentStatus | None = None
    current_version_id: UUID | None
    created_by_id: UUID
    signature_flow_mode: str


class DocumentUpdate(BaseModel):
    name: str | None = None
    status: DocumentStatus | None = None
    signature_flow_mode: str | None = None
    last_active_status: DocumentStatus | None = None

    @field_validator("signature_flow_mode", mode="before")
    @classmethod
    def normalize_flow_mode(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _normalize_signature_flow_mode(value)


# -------------------------------------------------------------------------
# Document version
# -------------------------------------------------------------------------

class DocumentVersionRead(IDModel, Timestamped):
    document_id: UUID
    storage_path: str
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None

    # 🔧 Agora opcional, para permitir versões geradas automaticamente (assinatura pública)
    uploaded_by_id: Optional[UUID] = None
    uploaded_by_full_name: Optional[str] = None

    # Campos ICP
    icp_signed: bool | None = None
    icp_timestamp: datetime | None = None
    icp_authority: str | None = None
    icp_report_url: str | None = None
    icp_public_report_url: str | None = None
    icp_signature_bundle_available: bool | None = None
    fields: Optional[List["DocumentFieldRead"]] = None


class DocumentVersionUpload(BaseModel):
    document_id: UUID
    file_name: str
    content_type: str
    size_bytes: int


class DocumentArchiveRequest(BaseModel):
    archived: bool = True


# -------------------------------------------------------------------------
# Document parties
# -------------------------------------------------------------------------

class DocumentPartyCreate(BaseModel):
    full_name: str
    email: EmailStr | None = None
    is_active: bool = True
    phone_number: str | None = None
    cpf: str | None = None
    role: str
    order_index: int = 1
    two_factor_type: str | None = None
    notification_channel: str = "email"
    company_name: str | None = None
    company_tax_id: str | None = None
    require_cpf: bool = True
    require_email: bool = True
    require_phone: bool = False
    allow_typed_name: bool = True
    allow_signature_image: bool = True
    allow_signature_draw: bool = True
    signature_method: str = "electronic"


class DocumentPartyUpdate(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    is_active: bool | None = None
    phone_number: str | None = None
    cpf: str | None = None
    role: str | None = None
    order_index: int | None = None
    two_factor_type: str | None = None
    notification_channel: str | None = None
    status: str | None = None
    company_name: str | None = None
    company_tax_id: str | None = None
    require_cpf: bool | None = None
    require_email: bool | None = None
    require_phone: bool | None = None
    allow_typed_name: bool | None = None
    allow_signature_image: bool | None = None
    allow_signature_draw: bool | None = None
    signature_method: str | None = None


class DocumentPartyRead(IDModel, Timestamped):
    document_id: UUID
    full_name: str
    is_active: bool
    email: EmailStr | None
    cpf: str | None
    role: str
    order_index: int
    two_factor_type: str | None
    status: str
    phone_number: str | None
    notification_channel: str
    company_name: str | None
    company_tax_id: str | None
    require_cpf: bool
    require_email: bool
    require_phone: bool
    allow_typed_name: bool
    allow_signature_image: bool
    allow_signature_draw: bool
    created_at: datetime
    signature_method: str
    requires_certificate: bool = False


# -------------------------------------------------------------------------
# Document signatures & fields
# -------------------------------------------------------------------------

class DocumentSignatureInfo(BaseModel):
    party_id: UUID | None = None
    full_name: str | None = None
    email: EmailStr | None = None
    role: str | None = None
    signature_method: str | None = None
    signature_type: str | None = None
    signed_at: datetime | None = None
    company_name: str | None = None
    company_tax_id: str | None = None
    status: str | None = None
    order_index: int | None = None


class DocumentFieldBase(BaseModel):
    role: str = Field(min_length=1, max_length=32)
    field_type: str = Field(default="signature", min_length=1, max_length=32)
    page: int = Field(default=1, ge=1)
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)
    label: str | None = Field(default=None, max_length=128)
    required: bool = True

    @field_validator("role")
    @classmethod
    def normalize_role(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("field_type")
    @classmethod
    def normalize_type(cls, value: str) -> str:
        return value.strip().lower()


class DocumentFieldCreate(DocumentFieldBase):
    pass


class DocumentFieldUpdate(BaseModel):
    role: str | None = Field(default=None, min_length=1, max_length=32)
    field_type: str | None = Field(default=None, min_length=1, max_length=32)
    page: int | None = Field(default=None, ge=1)
    x: float | None = Field(default=None, ge=0.0, le=1.0)
    y: float | None = Field(default=None, ge=0.0, le=1.0)
    width: float | None = Field(default=None, gt=0.0, le=1.0)
    height: float | None = Field(default=None, gt=0.0, le=1.0)
    label: str | None = Field(default=None, max_length=128)
    required: bool | None = None

    @field_validator("role")
    @classmethod
    def normalize_role(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("field_type")
    @classmethod
    def normalize_type(cls, value: str) -> str:
        return value.strip().lower()


class DocumentFieldRead(IDModel, Timestamped):
    document_id: UUID
    version_id: UUID
    role: str
    field_type: str
    page: int
    x: float
    y: float
    width: float
    height: float
    label: str | None
    required: bool
    created_at: datetime


# Corrige referências circulares
DocumentVersionRead.model_rebuild()
