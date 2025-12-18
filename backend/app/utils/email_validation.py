from __future__ import annotations

from functools import lru_cache

from email_validator import EmailNotValidError, validate_email

# Domains reserved for testing should not trigger DNS lookups.
_TEST_DOMAIN_ALLOWLIST = {
    "example.com",
    "example.org",
    "example.net",
}


@lru_cache(maxsize=512)
def _validate_deliverable_email(candidate: str) -> str:
    """Normalize email addresses enforcing deliverability checks."""
    info = validate_email(candidate, check_deliverability=True)
    return info.normalized or info.email


@lru_cache(maxsize=256)
def _validate_format_only(candidate: str) -> str:
    """Normalize addresses validating only syntax/IDNA information."""
    info = validate_email(candidate, check_deliverability=False)
    return info.normalized or info.email


def normalize_deliverable_email(value: str) -> str:
    """Return a normalized email ensuring its domain resolves for delivery."""
    candidate = (value or "").strip()
    if not candidate:
        raise ValueError("E-mail e obrigatorio.")

    lowered = candidate.lower()
    domain = lowered.split("@", 1)[1] if "@" in lowered else ""

    if domain in _TEST_DOMAIN_ALLOWLIST:
        return _validate_format_only(lowered)

    try:
        return _validate_deliverable_email(lowered)
    except EmailNotValidError as exc:  # pragma: no cover - library error text varies
        raise ValueError(f"E-mail invalido: {exc}") from exc
