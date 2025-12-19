from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4
import secrets
import string

import pyotp
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def _create_token(
    subject: str,
    tenant_id: str | None,
    expires_delta: timedelta,
    token_type: TokenType,
    extra_claims: Mapping[str, Any] | None = None,
) -> str:
    expire = datetime.utcnow() + expires_delta
    to_encode = {
        "sub": subject,
        "tenant_id": tenant_id,
        "exp": expire,
        "token_type": token_type.value,
        "jti": str(uuid4()),
    }
    if extra_claims:
        to_encode.update(extra_claims)
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def create_access_token(subject: str, tenant_id: str | None, extra_claims: Mapping[str, Any] | None = None) -> str:
    delta = timedelta(minutes=settings.access_token_expire_minutes)
    return _create_token(subject, tenant_id, delta, TokenType.ACCESS, extra_claims)


def create_refresh_token(subject: str, tenant_id: str | None, extra_claims: Mapping[str, Any] | None = None) -> str:
    delta = timedelta(minutes=settings.refresh_token_expire_minutes)
    return _create_token(subject, tenant_id, delta, TokenType.REFRESH, extra_claims)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def decode_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as exc:
        raise ValueError("Invalid token") from exc
    if "token_type" not in payload:
        raise ValueError("Invalid token payload")
    return payload


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def build_otpauth_url(secret: str, username: str, issuer: str) -> str:
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name=issuer)


def verify_totp(secret: str, otp: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(otp, valid_window=1)


def generate_secure_password(length: int = 14) -> str:
    if length < 8:
        raise ValueError("Password length must be at least 8 characters")
    alphabet = string.ascii_lowercase + string.ascii_uppercase + string.digits + "!@#$%^&*()-_=+"
    password = "".join(secrets.choice(alphabet) for _ in range(length))
    # Ensure basic diversity; retry if lacking required categories
    if (
        any(c.islower() for c in password)
        and any(c.isupper() for c in password)
        and any(c.isdigit() for c in password)
        and any(c in "!@#$%^&*()-_=+" for c in password)
    ):
        return password
    return generate_secure_password(length)
