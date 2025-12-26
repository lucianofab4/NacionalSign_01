from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Session, func, select

from app.models.notification import UserNotification


class UserNotificationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_notifications(
        self,
        *,
        recipient_id: UUID,
        limit: int = 20,
        offset: int = 0,
        only_unread: bool = False,
    ) -> tuple[list[UserNotification], int]:
        query = (
            select(UserNotification)
            .where(UserNotification.recipient_id == recipient_id)
            .order_by(UserNotification.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if only_unread:
            query = query.where(UserNotification.read_at.is_(None))

        items = list(self.session.exec(query).all())

        unread_query = (
            select(func.count())
            .where(UserNotification.recipient_id == recipient_id)
            .where(UserNotification.read_at.is_(None))
        )
        unread_count = self.session.exec(unread_query).one()

        return items, int(unread_count or 0)

    def mark_as_read(self, *, recipient_id: UUID, notification_id: UUID) -> UserNotification:
        notification = self.session.get(UserNotification, notification_id)
        if not notification or notification.recipient_id != recipient_id:
            raise ValueError("Notification not found")
        if not notification.read_at:
            notification.read_at = datetime.utcnow()
            self.session.add(notification)
            self.session.commit()
            self.session.refresh(notification)
        return notification

    def mark_all_as_read(self, *, recipient_id: UUID) -> int:
        updated = (
            self.session.exec(
                select(UserNotification).where(UserNotification.recipient_id == recipient_id).where(UserNotification.read_at.is_(None))
            ).all()
        )
        if not updated:
            return 0
        now = datetime.utcnow()
        for item in updated:
            item.read_at = now
            self.session.add(item)
        self.session.commit()
        return len(updated)
