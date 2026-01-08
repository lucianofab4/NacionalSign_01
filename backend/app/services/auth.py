from datetime import datetime
from uuid import UUID

from sqlmodel import Session, select

from app.core.config import settings
from app.models.tenant import Area, Tenant
from app.models.user import User, UserRole
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    Token,
    TwoFactorSetupResponse,
    TwoFactorVerifyRequest,
)
from app.utils.email_validation import normalize_deliverable_email
from app.utils.security import (
    TokenType,
    build_otpauth_url,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_totp_secret,
    generate_secure_password,
    get_password_hash,
    verify_password,
    verify_totp,
)


class AuthService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def register_tenant(self, payload: RegisterRequest) -> Token:
        existing = self.session.exec(select(Tenant).where(Tenant.slug == payload.tenant_slug)).first()
        if existing:
            raise ValueError("Tenant already exists")

        admin_email = normalize_deliverable_email(payload.admin_email)
        existing_user = self.session.exec(select(User).where(User.email == admin_email)).first()
        if existing_user:
            raise ValueError("User already exists")

        tenant = Tenant(name=payload.tenant_name, slug=payload.tenant_slug, cnpj=payload.cnpj)
        self.session.add(tenant)
        self.session.flush()

        default_area = Area(name="Geral", description="Area padrao", tenant_id=tenant.id)
        self.session.add(default_area)
        self.session.flush()

        admin_user = User(
            tenant_id=tenant.id,
            default_area_id=default_area.id,
            email=admin_email,
            cpf=payload.admin_cpf,
            full_name=payload.admin_full_name,
            password_hash=get_password_hash(payload.admin_password),
            profile="admin",
        )
        self.session.add(admin_user)
        self.session.commit()
        self.session.refresh(admin_user)

        return self._build_tokens(admin_user, active_tenant=tenant)

    def authenticate(self, payload: LoginRequest) -> Token:
        statement = select(User).where(User.email == payload.username).order_by(User.created_at.desc())
        candidates = self.session.exec(statement).all()

        if not candidates:
            raise ValueError("Invalid credentials")

        user = None
        for candidate in candidates:
            if not candidate.is_active:
                continue
            if verify_password(payload.password, candidate.password_hash):
                user = candidate
                break

        if not user:
            raise ValueError("Invalid credentials")

        if user.two_factor_enabled:
            if not payload.otp or not user.two_factor_secret:
                raise ValueError("Two-factor authentication required")
            if not verify_totp(user.two_factor_secret, payload.otp):
                raise ValueError("Invalid two-factor code")

        user.last_login_at = datetime.utcnow()
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)

        return self._build_tokens(user)

    def refresh(self, payload: RefreshRequest) -> Token:
        token_data = decode_token(payload.refresh_token)
        if token_data.get("token_type") != TokenType.REFRESH.value:
            raise ValueError("Invalid token type")

        user = self.session.get(User, token_data.get("sub"))
        if not user or not user.is_active:
            raise ValueError("Invalid token")

        tenant_override = self._resolve_active_tenant(self._safe_uuid(token_data.get("tenant_id")))
        return self._build_tokens(user, active_tenant=tenant_override)

    def initiate_two_factor(self, user: User) -> TwoFactorSetupResponse:
        secret = generate_totp_secret()
        user.two_factor_secret = secret
        user.two_factor_enabled = False
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        otpauth_url = build_otpauth_url(secret, user.email, settings.two_factor_issuer)
        return TwoFactorSetupResponse(secret=secret, otpauth_url=otpauth_url)

    def enable_two_factor(self, user: User, payload: TwoFactorVerifyRequest) -> None:
        if not user.two_factor_secret:
            raise ValueError("Two-factor secret not initialized")
        if not verify_totp(user.two_factor_secret, payload.otp):
            raise ValueError("Invalid two-factor code")
        user.two_factor_enabled = True
        self.session.add(user)
        self.session.commit()

    def disable_two_factor(self, user: User) -> None:
        user.two_factor_enabled = False
        user.two_factor_secret = None
        self.session.add(user)
        self.session.commit()

    def initiate_password_reset(self, email: str) -> tuple[User, str]:
        statement = select(User).where(User.email == email)
        user = self.session.exec(statement).first()
        if not user or not user.is_active:
            raise ValueError("Usuário não encontrado ou inativo.")

        temporary_password = generate_secure_password(12)
        user.password_hash = get_password_hash(temporary_password)
        if hasattr(user, "must_change_password"):
            user.must_change_password = True

        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user, temporary_password

    def impersonate_tenant(self, actor: User, tenant: Tenant) -> Token:
        db_actor = self.session.get(User, actor.id)
        if not db_actor or db_actor.profile != UserRole.SUPER_ADMIN.value:
            raise ValueError("Impersonation not allowed")
        if not tenant:
            raise ValueError("Tenant not found")
        return self._build_tokens(db_actor, active_tenant=tenant)

    def stop_impersonation(self, actor: User) -> Token:
        db_actor = self.session.get(User, actor.id)
        if not db_actor or db_actor.profile != UserRole.SUPER_ADMIN.value:
            raise ValueError("Action not allowed")
        return self._build_tokens(db_actor)

    def _resolve_active_tenant(self, tenant_id: UUID | None) -> Tenant | None:
        if not tenant_id:
            return None
        return self.session.get(Tenant, tenant_id)

    @staticmethod
    def _safe_uuid(value: str | None) -> UUID | None:  # pragma: no cover - defensive parsing
        if not value:
            return None
        try:
            return UUID(str(value))
        except ValueError:
            return None

    def _build_tokens(self, user: User, active_tenant: Tenant | None = None) -> Token:
        tenant = active_tenant or self._resolve_active_tenant(getattr(user, "tenant_id", None))
        active_tenant_id = tenant.id if tenant else getattr(user, "tenant_id", None)
        tenant_rel = getattr(user, "tenant", None)
        active_tenant_name = tenant.name if tenant else getattr(tenant_rel, "name", None)
        home_tenant_id = getattr(user, "tenant_id", None)
        impersonating = bool(tenant and home_tenant_id and tenant.id != home_tenant_id)

        extra_claims = {
            "home_tenant_id": str(home_tenant_id) if home_tenant_id else None,
            "impersonation": impersonating,
        }
        if impersonating and tenant:
            extra_claims["impersonated_tenant_id"] = str(tenant.id)

        tenant_scope = str(active_tenant_id) if active_tenant_id else None
        access_token = create_access_token(str(user.id), tenant_scope, extra_claims)
        refresh_token = create_refresh_token(str(user.id), tenant_scope, extra_claims)

        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
            must_change_password=bool(getattr(user, "must_change_password", False)),
            active_tenant_id=str(active_tenant_id) if active_tenant_id else None,
            active_tenant_name=active_tenant_name,
            home_tenant_id=str(home_tenant_id) if home_tenant_id else None,
            impersonating=impersonating,
            impersonated_tenant_id=str(tenant.id) if impersonating and tenant else None,
            impersonated_tenant_name=tenant.name if impersonating and tenant else None,
        )
