from datetime import datetime
from typing import Any, List
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditEventRead(BaseModel):
    id: UUID
    created_at: datetime
    event_type: str
    actor_id: UUID | None
    actor_role: str | None
    document_id: UUID | None
    ip_address: str | None
    user_agent: str | None
    details: dict[str, Any] | None

    model_config = ConfigDict(from_attributes=True)


class AuditEventList(BaseModel):
    items: List[AuditEventRead]
    total: int
    page: int
    page_size: int


class AuthLogRead(BaseModel):
    id: UUID
    created_at: datetime
    event_type: str
    ip_address: str | None
    user_agent: str | None
    success: bool

    model_config = ConfigDict(from_attributes=True)


class AuthLogList(BaseModel):
    items: List[AuthLogRead]
    total: int
    page: int
    page_size: int