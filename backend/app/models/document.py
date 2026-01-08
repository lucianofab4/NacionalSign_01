from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from sqlmodel import Field, Relationship

from app.models.base import TimestampedModel, UUIDModel
from app.models.customer import Customer
from app.models.tenant import Area, Tenant
from app.models.user import User


class DocumentStatus(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"
    ARCHIVED = "archived"
    DELETED = "deleted"


class DocumentGroup(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "document_groups"

    tenant_id: UUID = Field(foreign_key="tenants.id", index=True)
    area_id: UUID = Field(foreign_key="areas.id", index=True)
    owner_id: UUID = Field(foreign_key="users.id", index=True)
    title: str | None = Field(default=None, max_length=255)
    signature_flow_mode: str = Field(default="SEQUENTIAL", max_length=32)
    separate_documents: bool = Field(default=False)

    tenant: Tenant = Relationship()
    area: Area = Relationship()
    owner: User = Relationship()
    documents: List["Document"] = Relationship(back_populates="group")


class Document(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "documents"

    tenant_id: UUID = Field(foreign_key="tenants.id", index=True)
    area_id: UUID = Field(foreign_key="areas.id", index=True)
    customer_id: UUID | None = Field(default=None, foreign_key="customers.id", index=True)
    name: str
    status: DocumentStatus = Field(default=DocumentStatus.DRAFT)
    last_active_status: DocumentStatus | None = Field(default=None)
    current_version_id: UUID | None = Field(default=None, foreign_key="document_versions.id")
    signature_flow_mode: str = Field(default="SEQUENTIAL", max_length=32)
    group_id: UUID | None = Field(default=None, foreign_key="document_groups.id", index=True)
    deleted_at: datetime | None = Field(default=None, index=True)

    created_by_id: UUID = Field(foreign_key="users.id")

    tenant: Tenant = Relationship()
    customer: Optional[Customer] = Relationship(back_populates="documents")
    area: Area = Relationship(back_populates="documents")
    created_by: User = Relationship()
    group: Optional[DocumentGroup] = Relationship(back_populates="documents")
    versions: List["DocumentVersion"] = Relationship(
        back_populates="document",
        sa_relationship_kwargs={"foreign_keys": "DocumentVersion.document_id"},
    )
    fields: List["DocumentField"] = Relationship(back_populates="document")


class DocumentVersion(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "document_versions"

    document_id: UUID = Field(foreign_key="documents.id", index=True)
    storage_path: str
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str = Field(index=True)
    uploaded_by_id: UUID | None = Field(foreign_key="users.id", default=None)

    document: Document = Relationship(
        back_populates="versions",
        sa_relationship_kwargs={"foreign_keys": "DocumentVersion.document_id"},
    )
    fields: List["DocumentField"] = Relationship(back_populates="version")


class DocumentParty(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "document_parties"

    document_id: UUID = Field(foreign_key="documents.id", index=True)
    full_name: str
    is_active: bool = Field(default=True)
    email: str
    cpf: str | None = Field(default=None)
    role: str = Field(max_length=32)
    order_index: int = Field(default=1)
    two_factor_type: str | None = Field(default=None)
    status: str = Field(default="pending")
    phone_number: str | None = Field(default=None, max_length=32)
    notification_channel: str = Field(default="email", max_length=32)
    company_name: str | None = Field(default=None, max_length=128)
    company_tax_id: str | None = Field(default=None, max_length=32)
    require_cpf: bool = Field(default=True)
    require_email: bool = Field(default=True)
    require_phone: bool = Field(default=False)
    allow_typed_name: bool = Field(default=True)
    allow_signature_image: bool = Field(default=True)
    allow_signature_draw: bool = Field(default=True)
    signature_method: str = Field(default="electronic", max_length=32)


class AuditArtifact(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "document_artifacts"

    document_id: UUID = Field(foreign_key="documents.id", index=True)
    artifact_type: str = Field(index=True)
    storage_path: str
    sha256: str = Field(index=True)
    issued_at: Optional[datetime] = Field(default=None)


class DocumentField(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "document_fields"

    document_id: UUID = Field(foreign_key="documents.id", index=True)
    version_id: UUID = Field(foreign_key="document_versions.id", index=True)
    role: str = Field(max_length=32)
    field_type: str = Field(default="signature", max_length=32)
    page: int = Field(default=1, ge=1)
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)
    label: str | None = Field(default=None, max_length=128)
    required: bool = Field(default=True)

    document: Document = Relationship(back_populates="fields")
    version: DocumentVersion = Relationship(back_populates="fields")
