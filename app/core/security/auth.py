"""
app/core/security/security.py — JWT, password hashing, token helpers for Stitch.

Token signature conventions
----------------------------
- create_access_token(subject, extra)  subject → JWT "sub", extra merged into payload
- create_refresh_token(subject)        subject → JWT "sub"
- decode_token(token)                  returns full payload dict or None on any error

All callers in auth.py use the subject/extra pattern — this file matches that.
get_app_config() is the correct way to access settings throughout this codebase.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_app_config

pwd_context = CryptContext(schemes=["scrypt"], deprecated="auto")


# ─── Password ─────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _secret() -> str:
    cfg = get_app_config().security_config
    return cfg.auth_jwt_secret_key or cfg.jwt_secret_key


def _algorithm() -> str:
    return get_app_config().security_config.jwt_algorithm


def _access_ttl() -> int:
    return get_app_config().security_config.access_token_expire_minutes


def _refresh_ttl() -> int:
    return get_app_config().security_config.refresh_token_expire_minutes


# ─── Token creation ───────────────────────────────────────────────────────────

def create_access_token(
    subject: str,
    extra: Optional[dict] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a signed JWT access token.

    Args:
        subject:       The user's UUID string — stored as JWT "sub".
        extra:         Optional dict merged into the payload (roles, org_id, etc.).
        expires_delta: Override the default TTL from config.
    """
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=_access_ttl())
    )
    payload = {"sub": subject, "exp": expire, "type": "access"}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _secret(), algorithm=_algorithm())


def create_refresh_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a signed JWT refresh token.

    Args:
        subject:       The user's UUID string — stored as JWT "sub".
        expires_delta: Override the default TTL from config.
    """
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=_refresh_ttl())
    )
    payload = {"sub": subject, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, _secret(), algorithm=_algorithm())


def create_impersonation_token(
    target_user_id: str,
    impersonator_id: str,
    impersonator_email: str,
    expires_minutes: int = 120,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    return jwt.encode(
        {
            "sub": str(target_user_id),
            "impersonated_by": str(impersonator_id),
            "impersonated_by_email": impersonator_email,
            "exp": expire,
            "type": "impersonation",
        },
        _secret(),
        algorithm=_algorithm(),
    )


def decode_token(token: str) -> Optional[dict]:
    """Decode and verify a JWT. Returns the payload dict or None on any error."""
    try:
        return jwt.decode(token, _secret(), algorithms=[_algorithm()])
    except JWTError:
        return None


# ─── OTP / signed tokens ──────────────────────────────────────────────────────

def create_otp(length: int = 6) -> str:
    import secrets as _secrets
    return "".join([str(_secrets.randbelow(10)) for _ in range(length)])


def create_signed_token(user_id: str, token_type: str = "verify") -> Tuple[str, datetime]:
    """Generate a signed JWT for email verification or password reset."""
    cfg = get_app_config().security_config
    minutes = (
        cfg.password_reset_token_expire_minutes
        if token_type == "reset"
        else cfg.email_verification_token_expire_minutes
    )
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    token = jwt.encode(
        {"sub": user_id, "exp": expire, "type": token_type},
        _secret(),
        algorithm=_algorithm(),
    )
    return token, expire


def decode_signed_token(token: str, expected_type: str) -> Optional[str]:
    payload = decode_token(token)
    if not payload or payload.get("type") != expected_type:
        return None
    return payload.get("sub")

