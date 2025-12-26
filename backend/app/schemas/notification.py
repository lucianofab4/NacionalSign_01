from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import IDModel, Timestamped


class NotificationRead(IDModel, Timestamped):
    document_id: UUID
    event_type: str
    read_at: datetime | None = None
    document_name: str | None = None
    signer_name: str | None = None
    signer_email: str | None = None
    signer_role: str | None = None
    signed_at: datetime | None = None
    payload: dict[str, Any] | None = None


class NotificationList(BaseModel):
    items: list[NotificationRead]
    unread_count: int


class NotificationMarkAllResponse(BaseModel):
    updated: int
