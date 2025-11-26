from datetime import datetime

from sqlmodel import Session, select

from app.core.config import settings
from app.models.tenant import Area, Tenant
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    Token,
    TwoFactorSetupResponse,
    TwoFactorVerifyRequest,
)
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

        existing_user = self.session.exec(select(User).where(User.email == payload.admin_email)).first()
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
            email=payload.admin_email,
            cpf=payload.admin_cpf,
            full_name=payload.admin_full_name,
            password_hash=get_password_hash(payload.admin_password),
            profile="admin",
        )
        self.session.add(admin_user)
        self.session.commit()
        self.session.refresh(admin_user)

        return self._build_tokens(admin_user)

    def authenticate(self, payload: LoginRequest) -> Token:
        statement = select(User).where(User.email == payload.username)
        user = self.session.exec(statement).first()

        if not user or not user.is_active:
            raise ValueError("Invalid credentials")

        if not verify_password(payload.password, user.password_hash):
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

        return self._build_tokens(user)

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

    def _build_tokens(self, user: User) -> Token:
        access_token = create_access_token(str(user.id), str(user.tenant_id))
        refresh_token = create_refresh_token(str(user.id), str(user.tenant_id))
        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
            must_change_password=bool(getattr(user, "must_change_password", False)),
        )
