from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import JSON
from sqlmodel import Field

from app.models.base import TimestampedModel, UUIDModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.document import Document
    from app.models.user import User


class AuditLog(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "audit_logs"

    document_id: UUID | None = Field(default=None, foreign_key="documents.id", index=True)
    event_type: str = Field(index=True)
    actor_id: UUID | None = Field(default=None, foreign_key="users.id")
    actor_role: str | None = Field(default=None)
    ip_address: str | None = Field(default=None)
    user_agent: str | None = Field(default=None)
    details: dict | None = Field(default_factory=dict, sa_type=JSON)


class AuthLog(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "auth_logs"

    user_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
    event_type: str = Field(index=True)
    ip_address: str | None = Field(default=None)
    user_agent: str | None = Field(default=None)
    device_id: str | None = Field(default=None)
    success: bool = Field(default=True)
