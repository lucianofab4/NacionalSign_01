from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.deps import get_current_active_user, get_db, require_roles
from app.models.audit import AuditLog, AuthLog
from app.models.document import Document
from app.models.user import User, UserRole
from app.schemas.audit import AuditEventList, AuditEventRead, AuthLogList, AuthLogRead
from app.services.audit import AuditService

router = APIRouter(prefix="/audit", tags=["audit"])


def _service(session: Session) -> AuditService:
    return AuditService(session)


@router.get("/events", response_model=AuditEventList)
def list_events(
    event_type: Optional[str] = None,
    document_id: Optional[UUID] = None,
    actor_id: Optional[UUID] = None,
    start_at: Optional[datetime] = None,
    end_at: Optional[datetime] = None,
    page: int = 1,
    page_size: int = 50,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> AuditEventList:
    service = _service(session)
    items, total = service.list_events(
        tenant_id=current_user.tenant_id,
        event_type=event_type,
        document_id=document_id,
        actor_id=actor_id,
        start_at=start_at,
        end_at=end_at,
        page=page,
        page_size=page_size,
    )
    return AuditEventList(
        items=[AuditEventRead.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/events/{event_id}", response_model=AuditEventRead)
def get_event(
    event_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> AuditEventRead:
    service = _service(session)
    log = service.get_event(event_id)
    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit log not found")
    if log.document_id:
        document = session.get(Document, log.document_id)
        if document and document.tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit log not found")
    return AuditEventRead.model_validate(log)


@router.get("/auth", response_model=AuthLogList)
def list_auth_logs(
    success: Optional[bool] = None,
    start_at: Optional[datetime] = None,
    end_at: Optional[datetime] = None,
    page: int = 1,
    page_size: int = 50,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> AuthLogList:
    service = _service(session)
    items, total = service.list_auth(
        user_id=current_user.id,
        success=success,
        start_at=start_at,
        end_at=end_at,
        page=page,
        page_size=page_size,
    )
    return AuthLogList(
        items=[AuthLogRead.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/auth/{log_id}", response_model=AuthLogRead)
def get_auth_log(
    log_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> AuthLogRead:
    service = _service(session)
    log = service.get_auth(log_id)
    if not log or (log.user_id and log.user_id != current_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Auth log not found")
    return AuthLogRead.model_validate(log)
