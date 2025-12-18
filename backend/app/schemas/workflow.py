from datetime import datetime
from typing import Literal, Any, List
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.workflow import SignatureRequestStatus, SignatureType, WorkflowStatus
from app.schemas.common import IDModel, Timestamped


class WorkflowStepConfig(BaseModel):
    order: int = Field(gt=0)
    role: str = Field(min_length=1, max_length=32)
    action: str = Field(default="sign", min_length=1, max_length=32)
    execution: Literal["sequential", "parallel"] = "sequential"
    deadline_hours: int | None = Field(default=None, ge=1, le=24 * 90)

    @field_validator("role")
    @classmethod
    def normalize_role(cls, value: str) -> str:
        return value.strip().lower()


class WorkflowTemplateCreate(BaseModel):
    area_id: UUID
    name: str
    description: str | None = None
    steps: list[WorkflowStepConfig]


class WorkflowTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    steps: list[WorkflowStepConfig] | None = None
    is_active: bool | None = None


class WorkflowTemplateDuplicate(BaseModel):
    name: str
    area_id: UUID | None = None


class WorkflowTemplateRead(IDModel, Timestamped):
    tenant_id: UUID
    area_id: UUID
    name: str
    description: str | None
    is_active: bool
    steps: list[WorkflowStepConfig]


class WorkflowDispatch(BaseModel):
    template_id: UUID | None = None
    deadline_at: datetime | None = None
    steps: list[WorkflowStepConfig] | None = None


class WorkflowRead(IDModel, Timestamped):
    document_id: UUID
    template_id: UUID | None
    status: WorkflowStatus
    started_at: datetime | None
    completed_at: datetime | None


class WorkflowStepRead(IDModel, Timestamped):
    workflow_id: UUID
    party_id: UUID | None
    step_index: int
    action: str
    deadline_at: datetime | None
    completed_at: datetime | None


class SignatureFieldValue(BaseModel):
    text: str | None = None
    image: str | None = None
    image_mime: str | None = None
    image_name: str | None = None


class FieldSignature(BaseModel):
    field_id: str
    field_type: str
    typed_name: str | None = None
    signature_image: str | None = None
    signature_image_mime: str | None = None
    signature_image_name: str | None = None


class SignatureAction(BaseModel):
    action: str  # sign | refuse
    reason: str | None = None
    token: str | None = None
    typed_name: str | None = None
    signature_image: str | None = None  # base64-encoded payload or data URL
    signature_image_mime: str | None = None
    signature_image_name: str | None = None
    consent: bool | None = None
    consent_text: str | None = None
    consent_version: str | None = None
    confirm_email: str | None = None
    confirm_phone_last4: str | None = None
    confirm_cpf: str | None = None
    certificate_subject: str | None = None
    certificate_issuer: str | None = None
    certificate_serial: str | None = None
    certificate_thumbprint: str | None = None
    signature_protocol: str | None = None
    signature_type: str | None = None
    signature_authentication: str | None = None
    signed_pdf: str | None = None
    signed_pdf_name: str | None = None
    signed_pdf_mime: str | None = None
    signed_pdf_digest: str | None = None
    field_values: dict[str, SignatureFieldValue] | None = None
    fields: List[FieldSignature] = Field(default_factory=list)


class SignatureRequestRead(IDModel, Timestamped):
    workflow_step_id: UUID
    status: SignatureRequestStatus
    token_channel: str | None


class SignatureRead(IDModel, Timestamped):
    signature_request_id: UUID
    signature_type: SignatureType
    signed_at: datetime | None
    signer_ip: str | None
    signer_user_agent: str | None
    reason: str | None
    typed_name: str | None
    typed_name_hash: str | None
    evidence_options: dict[str, Any] | None = None
    consent_given: bool
    consent_text: str | None
    consent_version: str | None
    consent_given_at: datetime | None
    evidence_image_artifact_id: UUID | None
    evidence_image_mime_type: str | None
    evidence_image_size: int | None
    evidence_image_sha256: str | None
    evidence_image_filename: str | None
