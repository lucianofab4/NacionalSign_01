from uuid import UUID

from pydantic import BaseModel, EmailStr


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    must_change_password: bool = False
    active_tenant_id: str | None = None
    active_tenant_name: str | None = None
    home_tenant_id: str | None = None
    impersonating: bool = False
    impersonated_tenant_id: str | None = None
    impersonated_tenant_name: str | None = None


class TokenPayload(BaseModel):
    sub: str
    tenant_id: str | None = None
    token_type: str
    exp: int
    home_tenant_id: str | None = None
    impersonation: bool | None = None
    impersonated_tenant_id: str | None = None


class LoginRequest(BaseModel):
    username: EmailStr
    password: str
    otp: str | None = None


class RegisterRequest(BaseModel):
    tenant_name: str
    tenant_slug: str
    admin_full_name: str
    admin_email: EmailStr
    admin_cpf: str
    admin_password: str
    cnpj: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class ImpersonateTenantRequest(BaseModel):
    tenant_id: UUID
    reason: str | None = None


class TwoFactorSetupResponse(BaseModel):
    secret: str
    otpauth_url: str


class TwoFactorVerifyRequest(BaseModel):
    otp: str
