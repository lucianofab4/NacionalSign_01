from __future__ import annotations

from datetime import datetime
from typing import Dict, List
from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.models.document import DocumentStatus


class DocumentReportParty(BaseModel):
    party_id: UUID
    document_id: UUID
    full_name: str
    email: EmailStr | None = None
    role: str
    company_name: str | None = None
    company_tax_id: str | None = None
    signature_method: str | None = None
    signature_type: str | None = None
    status: str
    order_index: int
    signed_at: datetime | None = None
    requires_certificate: bool = False


class DocumentReportRow(BaseModel):
    document_id: UUID
    name: str
    status: DocumentStatus
    area_id: UUID
    area_name: str
    created_at: datetime
    updated_at: datetime | None = None
    created_by_id: UUID
    created_by_name: str | None = None
    created_by_email: EmailStr | None = None
    workflow_started_at: datetime | None = None
    workflow_completed_at: datetime | None = None
    total_parties: int
    signed_parties: int
    pending_parties: int
    signed_digital: int
    signed_electronic: int
    parties: List[DocumentReportParty]


class DocumentReportResponse(BaseModel):
    items: List[DocumentReportRow]
    total: int
    status_summary: Dict[str, int]
