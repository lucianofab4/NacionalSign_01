from pydantic import BaseModel, EmailStr


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    must_change_password: bool = False


class TokenPayload(BaseModel):
    sub: str
    tenant_id: str
    token_type: str
    exp: int


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


class TwoFactorSetupResponse(BaseModel):
    secret: str
    otpauth_url: str


class TwoFactorVerifyRequest(BaseModel):
    otp: str
