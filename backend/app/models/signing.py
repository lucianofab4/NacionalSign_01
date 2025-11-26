from __future__ import annotations

from enum import Enum
from uuid import UUID

from sqlalchemy import JSON
from sqlmodel import Field

from app.models.base import TimestampedModel, UUIDModel


class SigningAgentAttemptStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    ERROR = "error"


class SigningAgentAttempt(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "signing_agent_attempts"

    document_id: UUID = Field(foreign_key="documents.id", index=True)
    version_id: UUID = Field(foreign_key="document_versions.id", index=True)
    actor_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
    actor_role: str | None = Field(default=None, max_length=64)
    payload: dict | None = Field(default=None, sa_type=JSON)
    status: SigningAgentAttemptStatus = Field(default=SigningAgentAttemptStatus.PENDING)
    error_message: str | None = Field(default=None)
    protocol: str | None = Field(default=None, max_length=128)
    agent_details: dict | None = Field(default=None, sa_type=JSON)

