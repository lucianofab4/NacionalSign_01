from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.api.deps import get_current_active_user, get_db
from app.models.document import DocumentStatus
from app.models.user import User
from app.schemas.reporting import DocumentReportResponse
from app.services.reporting import DocumentReportFilters, ReportingService

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/documents", response_model=DocumentReportResponse)
def list_document_reports(
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    status: DocumentStatus | None = Query(default=None),
    area_id: UUID | None = Query(default=None),
    signature_method: str | None = Query(default=None, description="Filtro por metodo de assinatura (digital/electronic)"),
    search: str | None = Query(default=None, description="Filtro por nome do documento"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> DocumentReportResponse:
    service = ReportingService(session)
    filters = DocumentReportFilters(
        start_date=start_date,
        end_date=end_date,
        status=status,
        area_id=area_id,
        signature_method=signature_method,
        search=search,
    )
    return service.list_documents(
        tenant_id=current_user.tenant_id,
        filters=filters,
        limit=limit,
        offset=offset,
    )
