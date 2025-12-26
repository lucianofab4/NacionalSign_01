from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON
from sqlmodel import Field

from app.models.base import TimestampedModel, UUIDModel


class UserNotification(UUIDModel, TimestampedModel, table=True):
    __tablename__ = "user_notifications"

    tenant_id: UUID = Field(foreign_key="tenants.id", index=True)
    document_id: UUID = Field(foreign_key="documents.id", index=True)
    recipient_id: UUID = Field(foreign_key="users.id", index=True)
    party_id: UUID | None = Field(default=None, foreign_key="document_parties.id", index=True)
    event_type: str = Field(max_length=64)
    payload: dict | None = Field(default=None, sa_type=JSON)
    read_at: datetime | None = Field(default=None, index=True)
