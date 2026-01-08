from typing import Annotated, Callable
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session, select

from app.core.config import settings
from app.db.session import get_session
from app.models.user import User, UserRole
from app.utils.security import TokenType, decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_v1_str}/auth/login")


def get_db() -> Session:
    yield from get_session()


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[Session, Depends(get_db)],
) -> User:
    try:
        payload = decode_token(token)
    except ValueError as exc:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    if payload.get("token_type") != TokenType.ACCESS.value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    try:
        user_id = UUID(str(payload["sub"]))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject") from exc

    statement = select(User).where(User.id == user_id)
    user = session.exec(statement).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    token_tenant_raw = payload.get("tenant_id")
    impersonation_flag = bool(payload.get("impersonation"))
    impersonated_raw = payload.get("impersonated_tenant_id")
    home_tenant_raw = payload.get("home_tenant_id")

    if impersonation_flag and user.profile != UserRole.SUPER_ADMIN.value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid impersonation token")

    effective_tenant_id = user.tenant_id
    if token_tenant_raw:
        try:
            effective_tenant_id = UUID(str(token_tenant_raw))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid tenant scope") from exc

    if effective_tenant_id != user.tenant_id:
        session.expunge(user)
        object.__setattr__(user, "_original_tenant_id", user.tenant_id)
        user.tenant_id = effective_tenant_id
    else:
        object.__setattr__(user, "_original_tenant_id", user.tenant_id)

    object.__setattr__(user, "active_tenant_id", effective_tenant_id)

    impersonated_uuid = None
    if impersonated_raw:
        try:
            impersonated_uuid = UUID(str(impersonated_raw))
        except ValueError:
            impersonated_uuid = None

    object.__setattr__(user, "impersonated_tenant_id", impersonated_uuid)
    object.__setattr__(user, "is_impersonating", impersonation_flag and impersonated_uuid is not None)

    if home_tenant_raw:
        try:
            home_uuid = UUID(str(home_tenant_raw))
        except ValueError:
            home_uuid = user.tenant_id
    else:
        home_uuid = getattr(user, "_original_tenant_id", user.tenant_id)
    object.__setattr__(user, "home_tenant_id", home_uuid)

    return user


def get_current_active_user(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User inactive")
    return current_user


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    allowed = {role.value for role in roles}

    def dependency(current_user: Annotated[User, Depends(get_current_active_user)]) -> User:
        if current_user.profile in {UserRole.OWNER.value, UserRole.SUPER_ADMIN.value}:
            return current_user
        if current_user.profile not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user

    return dependency


def require_platform_admin(current_user: Annotated[User, Depends(get_current_active_user)]) -> User:
    allowed_emails = {
        (email or "").strip().lower()
        for email in getattr(settings, "customer_admin_emails", []) or []
        if email
    }
    current_email = (current_user.email or "").strip().lower()
    if current_user.profile == UserRole.SUPER_ADMIN.value or current_email in allowed_emails:
        return current_user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
