from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.api.deps import get_current_active_user, get_db
from app.models.notification import UserNotification
from app.models.user import User
from app.schemas.notification import NotificationList, NotificationMarkAllResponse, NotificationRead
from app.services.user_notifications import UserNotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _to_schema(item: UserNotification) -> NotificationRead:
    payload = item.payload or {}
    return NotificationRead(
        id=item.id,
        created_at=item.created_at,
        updated_at=item.updated_at,
        document_id=item.document_id,
        event_type=item.event_type,
        read_at=item.read_at,
        document_name=payload.get("document_name"),
        signer_name=payload.get("signer_name"),
        signer_email=payload.get("signer_email"),
        signer_role=payload.get("signer_role"),
        signed_at=payload.get("signed_at"),
        payload=payload or None,
    )


@router.get("", response_model=NotificationList)
def list_notifications(
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    only_unread: bool = Query(default=False),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> NotificationList:
    service = UserNotificationService(session)
    items, unread_count = service.list_notifications(
        recipient_id=current_user.id,
        limit=limit,
        offset=offset,
        only_unread=only_unread,
    )
    return NotificationList(items=[_to_schema(item) for item in items], unread_count=unread_count)


@router.post("/{notification_id}/read", response_model=NotificationRead)
def mark_notification_as_read(
    notification_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> NotificationRead:
    service = UserNotificationService(session)
    try:
        updated = service.mark_as_read(recipient_id=current_user.id, notification_id=notification_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found") from exc
    return _to_schema(updated)


@router.post("/read-all", response_model=NotificationMarkAllResponse)
def mark_all_notifications_as_read(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> NotificationMarkAllResponse:
    service = UserNotificationService(session)
    updated = service.mark_all_as_read(recipient_id=current_user.id)
    return NotificationMarkAllResponse(updated=updated)
