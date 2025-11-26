from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlmodel import Session

from app.api.deps import get_current_active_user, get_db, require_roles
from app.core.config import settings
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserRead, UserUpdate, UserSettingsUpdate, UserPasswordResetResponse
from app.services.audit import AuditService
from app.services.notification import NotificationService
from app.services.user import UserService

router = APIRouter(prefix="/users", tags=["users"])

class SendCredentialsRequest(BaseModel):
    user_id: UUID
    email: EmailStr
    full_name: str
    username: str
    temp_password: str


def _build_notification_service(session: Session | None = None) -> NotificationService | None:
    if not settings.smtp_host or not settings.smtp_sender:
        return None
    audit_service = AuditService(session) if session else None
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

@router.get("", response_model=List[UserRead])
def list_users(
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> List[UserRead]:
    service = UserService(session)
    return list(service.list_users(current_user.tenant_id))


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> UserRead:
    service = UserService(session)
    model_data = payload.model_dump()
    phone_value = payload.phone_number.strip() if payload.phone_number else None
    model_data["phone_number"] = phone_value

    if current_user.profile == UserRole.AREA_MANAGER.value:
        if payload.profile in (UserRole.ADMIN, UserRole.AREA_MANAGER):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        default_area_id = payload.default_area_id or current_user.default_area_id
        if default_area_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Area is required")
        model_data["default_area_id"] = default_area_id

    try:
        return service.create_user(current_user.tenant_id, UserCreate(**model_data))
    except ValueError as exc:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_active_user)) -> UserRead:
    return current_user


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> UserRead:
    service = UserService(session)
    user = service.get_user(user_id)
    if not user or user.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.patch("/me", response_model=UserRead)
def update_me(
    payload: UserSettingsUpdate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> UserRead:
    service = UserService(session)
    updated = service.update_user_settings(
        current_user,
        payload_full_name=payload.full_name,
        payload_phone_number=payload.phone_number,
        payload_password=payload.password,
        payload_two_factor=payload.two_factor_enabled,
        payload_default_area=payload.default_area_id,
    )
    return updated


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> UserRead:
    service = UserService(session)
    user = service.get_user(user_id)
    if not user or user.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if current_user.profile == UserRole.AREA_MANAGER.value:
        if user.profile in (UserRole.ADMIN.value, UserRole.AREA_MANAGER.value):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        if payload.profile in (UserRole.ADMIN, UserRole.AREA_MANAGER):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        if payload.default_area_id and payload.default_area_id != current_user.default_area_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot move user to another area")

    try:
        return service.update_user(current_user.tenant_id, user, payload)
    except ValueError as exc:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{user_id}/reset-password", response_model=UserPasswordResetResponse)
def reset_user_password(
    user_id: UUID,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> UserPasswordResetResponse:
    service = UserService(session)
    target_user = service.get_user(user_id)
    if not target_user or target_user.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    try:
        temporary_password = service.reset_user_password(user=target_user, actor_tenant_id=current_user.tenant_id)
    except ValueError as exc:  # pragma: no cover - safety guard
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    audit = AuditService(session)
    audit.record_event(
        event_type="user_password_reset",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={
            "target_user_id": str(target_user.id),
            "target_user_email": target_user.email,
        },
    )

    return UserPasswordResetResponse(user_id=target_user.id, email=target_user.email, temporary_password=temporary_password)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_user(
    user_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> None:
    service = UserService(session)
    user = service.get_user(user_id)
    if not user or user.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    service.deactivate_user(user)


@router.post("/send-credentials", status_code=status.HTTP_202_ACCEPTED)
def send_credentials_email(
    payload: SendCredentialsRequest,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> dict[str, str]:
    user_service = UserService(session)
    target_user = user_service.get_user(payload.user_id)
    if not target_user or target_user.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    notifier = _build_notification_service(session)
    if not notifier:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuração de e-mail não disponível para envio.",
        )

    try:
        notifier.send_user_credentials_email(
            to=payload.email,
            full_name=payload.full_name,
            username=payload.username,
            temporary_password=payload.temp_password,
        )
    except Exception as exc:  # pragma: no cover - depends on SMTP provider
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    audit = AuditService(session)
    audit.record_event(
        event_type="user_credentials_email_sent",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        document_id=None,
        details={
            "target_user_id": str(payload.user_id),
            "target_user_email": payload.email,
        },
    )
    return {"status": "sent"}


