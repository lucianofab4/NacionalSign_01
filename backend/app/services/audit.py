from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlmodel import Session, select

from app.models.audit import AuditLog, AuthLog
from app.models.document import Document


class AuditService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record_auth(
        self,
        user_id: UUID | None,
        event_type: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        success: bool = True,
    ) -> None:
        log = AuthLog(
            user_id=user_id,
            event_type=event_type,
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
        )
        self.session.add(log)
        self.session.commit()

    def record_event(
        self,
        event_type: str,
        actor_id: UUID | None = None,
        actor_role: str | None = None,
        document_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        details: dict | None = None,
    ) -> None:
        log = AuditLog(
            document_id=document_id,
            event_type=event_type,
            actor_id=actor_id,
            actor_role=actor_role,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details or {},
        )
        self.session.add(log)
        self.session.commit()

    def list_events(
        self,
        tenant_id: UUID | None = None,
        event_type: Optional[str] = None,
        document_id: Optional[UUID] = None,
        actor_id: Optional[UUID] = None,
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AuditLog], int]:
        from sqlalchemy import func

        query = (
            select(AuditLog)
            .join(Document, AuditLog.document_id == Document.id, isouter=True)
        )

        if tenant_id:
            query = query.where((Document.tenant_id == tenant_id) | (AuditLog.document_id.is_(None)))
        if event_type:
            query = query.where(AuditLog.event_type == event_type)
        if document_id:
            query = query.where(AuditLog.document_id == document_id)
        if actor_id:
            query = query.where(AuditLog.actor_id == actor_id)
        if start_at:
            query = query.where(AuditLog.created_at >= start_at)
        if end_at:
            query = query.where(AuditLog.created_at <= end_at)

        total = self.session.exec(
            select(func.count()).select_from(query.subquery())
        ).one()

        items = self.session.exec(
            query.order_by(AuditLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return items, total

    def list_auth(
        self,
        user_id: UUID | None = None,
        success: Optional[bool] = None,
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AuthLog], int]:
        from sqlalchemy import func

        query = select(AuthLog)
        if user_id:
            query = query.where(AuthLog.user_id == user_id)
        if success is not None:
            query = query.where(AuthLog.success == success)
        if start_at:
            query = query.where(AuthLog.created_at >= start_at)
        if end_at:
            query = query.where(AuthLog.created_at <= end_at)

        total = self.session.exec(
            select(func.count()).select_from(query.subquery())
        ).one()

        items = self.session.exec(
            query.order_by(AuthLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return items, total

    def get_event(self, log_id: UUID) -> AuditLog | None:
        return self.session.get(AuditLog, log_id)

    def get_auth(self, log_id: UUID) -> AuthLog | None:
        return self.session.get(AuthLog, log_id)
