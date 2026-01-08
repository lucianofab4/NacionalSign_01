from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from sqlmodel import Field, Relationship
from sqlalchemy import JSON

from app.models.base import TimestampedModel, UUIDModel
from app.models.document import Document, DocumentGroup, DocumentParty


class WorkflowStatus(str, Enum):
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class WorkflowTemplate(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "workflow_templates"

    tenant_id: UUID = Field(foreign_key="tenants.id", index=True)
    area_id: UUID = Field(foreign_key="areas.id", index=True)
    name: str
    description: Optional[str] = Field(default=None)
    config_json: str = Field(default="{}")
    is_active: bool = Field(default=True)


class WorkflowInstance(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "workflows"

    document_id: UUID = Field(foreign_key="documents.id", index=True)
    group_id: UUID | None = Field(default=None, foreign_key="document_groups.id", index=True)
    template_id: UUID | None = Field(default=None, foreign_key="workflow_templates.id")
    status: WorkflowStatus = Field(default=WorkflowStatus.DRAFT)
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    is_group_workflow: bool = Field(default=False)

    document: Document = Relationship()
    group: Optional[DocumentGroup] = Relationship()
    steps: List["WorkflowStep"] = Relationship(back_populates="workflow")


class WorkflowStep(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "workflow_steps"

    workflow_id: UUID = Field(foreign_key="workflows.id", index=True)
    party_id: UUID | None = Field(default=None, foreign_key="document_parties.id")
    step_index: int
    phase_index: int = Field(default=1)
    execution_type: str = Field(default="sequential")
    action: str = Field(default="sign")
    deadline_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)

    workflow: WorkflowInstance = Relationship(back_populates="steps")
    party: Optional[DocumentParty] = Relationship()
    signature_requests: List["SignatureRequest"] = Relationship(back_populates="step")


class SignatureRequestStatus(str, Enum):
    PENDING = "pendente"
    SENT = "enviado"
    SIGNED = "assinado"
    REFUSED = "recusado"
    DELEGATED = "delegado"
    EXPIRED = "expirado"


class SignatureRequest(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "signature_requests"

    workflow_step_id: UUID = Field(foreign_key="workflow_steps.id", index=True)
    document_id: UUID = Field(foreign_key="documents.id", index=True)
    group_id: UUID | None = Field(default=None, foreign_key="document_groups.id", index=True)
    token_channel: str | None = Field(default=None)
    token_hash: str | None = Field(default=None)
    token_expires_at: Optional[datetime] = Field(default=None)
    status: SignatureRequestStatus = Field(default=SignatureRequestStatus.PENDING)

    step: WorkflowStep = Relationship(back_populates="signature_requests")
    document: Document = Relationship(sa_relationship_kwargs={"foreign_keys": "SignatureRequest.document_id"})
    group: Optional[DocumentGroup] = Relationship()
    signature: List["Signature"] = Relationship(back_populates="request")


class SignatureType(str, Enum):
    ELECTRONIC = "electronic"
    DIGITAL = "digital"
    TOKEN = "token"


class Signature(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "signatures"

    signature_request_id: UUID = Field(foreign_key="signature_requests.id", index=True)
    signature_type: SignatureType = Field(default=SignatureType.ELECTRONIC)
    signed_at: Optional[datetime] = Field(default=None)
    signer_ip: str | None = Field(default=None)
    signer_user_agent: str | None = Field(default=None)
    digest_sha256: str | None = Field(default=None)
    certificate_serial: str | None = Field(default=None)
    reason: str | None = Field(default=None)
    typed_name: str | None = Field(default=None, max_length=256)
    typed_name_hash: str | None = Field(default=None, max_length=128, index=True)
    field_values: dict | None = Field(default=None, sa_type=JSON)
    evidence_options: dict | None = Field(default=None, sa_type=JSON)
    consent_given: bool = Field(default=False)
    consent_text: str | None = Field(default=None)
    consent_version: str | None = Field(default=None, max_length=64)
    consent_given_at: Optional[datetime] = Field(default=None)
    evidence_image_artifact_id: UUID | None = Field(
        default=None,
        foreign_key="document_artifacts.id",
        index=True,
    )
    evidence_image_mime_type: str | None = Field(default=None, max_length=64)
    evidence_image_size: int | None = Field(default=None)
    evidence_image_sha256: str | None = Field(default=None, max_length=128)
    evidence_image_filename: str | None = Field(default=None, max_length=256)

    request: SignatureRequest = Relationship(back_populates="signature")
