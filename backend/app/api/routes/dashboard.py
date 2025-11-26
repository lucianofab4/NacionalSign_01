from uuid import UUID

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_current_active_user, get_db
from app.models.user import User
from app.schemas.dashboard import DashboardMetrics
from app.services.document import DocumentService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/metrics", response_model=DashboardMetrics)
def read_dashboard_metrics(
    area_id: UUID | None = None,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_db),
) -> DashboardMetrics:
    document_service = DocumentService(session)
    metrics = document_service.get_dashboard_metrics(current_user=current_user, area_id=area_id)
    return DashboardMetrics(**metrics)

