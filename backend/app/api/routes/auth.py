from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlmodel import Session

from app.api.deps import get_db
from app.core.config import settings
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    Token,
)
from app.services.audit import AuditService
from app.services.auth import AuthService
from app.services.notification import NotificationService

router = APIRouter(prefix="/auth", tags=["auth"])


def _services(session: Session) -> tuple[AuthService, AuditService]:
    return AuthService(session), AuditService(session)


def _build_notification_service(audit_service: AuditService | None = None) -> NotificationService | None:
    if not settings.smtp_host or not settings.smtp_sender:
        return None
    service = NotificationService(
        audit_service=audit_service,
        public_base_url=settings.resolved_public_app_url(),
        agent_download_url=settings.signing_agent_download_url,
    )
    service.configure_email(
        host=settings.smtp_host,
        port=settings.smtp_port,
        sender=settings.smtp_sender,
        username=settings.smtp_username,
        password=settings.smtp_password,
        starttls=settings.smtp_starttls,
    )
    return service


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, session: Session = Depends(get_db)) -> Token:
    auth_service, audit_service = _services(session)
    try:
        token = auth_service.register_tenant(payload)
    except ValueError as exc:  # pragma: no cover - validation handled here
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_service.record_event(event_type="tenant_registered", details={"tenant": payload.tenant_slug})
    return token


@router.post("/login", response_model=Token)
def login(
    payload: LoginRequest,
    request: Request,
    session: Session = Depends(get_db),
) -> Token:
    auth_service, audit_service = _services(session)
    try:
        token = auth_service.authenticate(payload)
        audit_service.record_auth(
            user_id=None,
            event_type="login",
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            success=True,
        )
        return token
    except ValueError as exc:  # pragma: no cover
        audit_service.record_auth(
            user_id=None,
            event_type="login",
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            success=False,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/refresh", response_model=Token)
def refresh(payload: RefreshRequest, session: Session = Depends(get_db)) -> Token:
    auth_service, audit_service = _services(session)
    try:
        token = auth_service.refresh(payload)
        audit_service.record_event(event_type="token_refreshed", details={"user": token.access_token})
        return token
    except ValueError as exc:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


@router.post("/forgot-password")
def forgot_password(
    payload: ForgotPasswordRequest,
    session: Session = Depends(get_db),
) -> dict[str, object]:
    auth_service, audit_service = _services(session)
    try:
        user, temporary_password = auth_service.initiate_password_reset(payload.email)
    except ValueError:
        # Avoid exposing whether the email exists
        return {"status": "ok"}

    notifier = _build_notification_service(audit_service)
    if notifier:
        try:
            notifier.send_user_credentials_email(
                to=user.email,
                full_name=user.full_name,
                username=user.email,
                temporary_password=temporary_password,
                subject="Redefinição de senha - NacionalSign",
            )
        except Exception as exc:  # pragma: no cover - provider dependent
            audit_service.record_event(
                event_type="forgot_password_email_error",
                details={"user_email": user.email, "reason": str(exc)},
            )

    audit_service.record_event(
        event_type="forgot_password_requested",
        details={
            "user_email": user.email,
        },
    )
    return {"status": "ok", "must_change_password": True}
