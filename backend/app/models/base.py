from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class TimestampedModel(SQLModel):
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime | None = Field(default=None, nullable=True)


class UUIDModel(SQLModel):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
