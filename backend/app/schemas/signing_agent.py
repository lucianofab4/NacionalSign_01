from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.signing import SigningAgentAttemptStatus


class SignPdfRequest(BaseModel):
    protocol: Optional[str] = Field(default=None, max_length=128)
    watermark: Optional[str] = Field(default=None, max_length=256)
    footer_note: Optional[str] = Field(default=None, max_length=512)
    signature_type: Optional[str] = Field(default=None, max_length=128)
    authentication: Optional[str] = Field(default=None, max_length=128)
    certificate_description: Optional[str] = Field(default=None, max_length=256)
    token_info: Optional[str] = Field(default=None, max_length=256)
    actions: Optional[List[str]] = None
    cert_index: Optional[int] = Field(default=None, ge=0)
    thumbprint: Optional[str] = Field(default=None, max_length=128)
    confirm_cpf: Optional[str] = Field(default=None, max_length=32)

    signature_page: Optional[int] = Field(default=None, ge=1, le=9999)
    signature_width: Optional[float] = Field(default=None, gt=0)
    signature_height: Optional[float] = Field(default=None, gt=0)
    signature_margin_x: Optional[float] = Field(default=None, ge=0)
    signature_margin_y: Optional[float] = Field(default=None, ge=0)

    @field_validator("actions")
    @classmethod
    def _clean_actions(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        cleaned = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return cleaned or None


class SignPdfResponse(BaseModel):
    version_id: UUID
    document_id: UUID
    protocol: str
    signature_type: str | None = None
    authentication: str | None = None


class SignAgentAttemptRead(BaseModel):
    id: UUID
    document_id: UUID
    version_id: UUID
    actor_id: UUID | None
    actor_role: str | None
    payload: dict[str, Any] | None
    status: SigningAgentAttemptStatus
    error_message: str | None
    protocol: str | None
    agent_details: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class SigningCertificate(BaseModel):
    index: int
    subject: str
    issuer: str
    serial_number: str | None = None
    thumbprint: str | None = None
    not_before: datetime | None = None
    not_after: datetime | None = None


class PublicAgentSessionStartPayload(BaseModel):
    cert_index: int | None = Field(default=None, ge=0)
    thumbprint: str | None = Field(default=None, max_length=128)
    confirm_cpf: str | None = Field(default=None, max_length=32)


class PublicAgentSessionStartResponse(BaseModel):
    attempt_id: UUID
    payload: dict[str, Any]


class PublicAgentSessionCompletePayload(BaseModel):
    agent_response: dict[str, Any]
