# # app/api/core/exceptions/custom_exceptions.py
# v2
"""
app/core/exceptions/custom_exceptions.py — Stitch API exception hierarchy.

Design goals
------------
1. Every exception carries a stable `error_code` string. Frontends and
   future SDKs should switch on `error_code`, never on `message` text
   (message is human-facing and may be reworded without notice).
2. `details` is a free-form dict for machine-readable context (field
   errors, the resource id involved, retry hints, etc.) — never put PII
   or secrets in it, since it round-trips straight into the HTTP response.
3. Short "IMF-style" aliases (ConflictError, ForbiddenError, NotFoundError,
   UnauthorizedError, BadRequestError) are the primary names used in
   route code. The original verbose names are kept as aliases for
   backwards compatibility with any code already importing them.
4. Nothing here talks to FastAPI directly — that wiring lives in
   app/core/exceptions/handlers.py so this module has zero framework
   coupling and can be unit tested in isolation.
"""

from typing import Any, Dict, List, Optional


class CustomAPIException(Exception):
    """Base exception for all Stitch API errors.

    Anything raised in route/service code that should produce a
    structured JSON error response must subclass this (or be caught
    and wrapped by the global handler as INTERNAL_ERROR).
    """

    def __init__(
        self,
        message: str = "An error occurred",
        status_code: int = 500,
        error_code: str = "INTERNAL_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """Canonical serialization used by the global exception handler."""
        return {
            "success": False,
            "message": self.message,
            "error_code": self.error_code,
            "details": self.details,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"{self.__class__.__name__}(status_code={self.status_code}, "
            f"error_code={self.error_code!r}, message={self.message!r})"
        )


# ──────────────────────────────────────────────────────────────────────────
# 400 — User does not have enough subscription units to complete the requested operation.
# ──────────────────────────────────────────────────────────────────────────

class InsufficientUnitsError(CustomAPIException):
    """User does not have enough subscription units to complete the requested operation."""

    def __init__(
        self,
        requested: int,
        available: int,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        details = dict(details or {})
        details.setdefault("requested", requested)
        details.setdefault("available", available)
        if message is None:
            message = (
                f"Insufficient units: {requested} requested, "
                f"only {available} available."
            )
        super().__init__(
            message=message,
            status_code=400,
            error_code="INSUFFICIENT_UNITS",
            details=details,
        )

# ──────────────────────────────────────────────────────────────────────────
# 400 — Bad Request
# ──────────────────────────────────────────────────────────────────────────

class BadRequestError(CustomAPIException):
    """Generic malformed/invalid request that isn't a field-validation error."""

    def __init__(
        self,
        message: str = "Bad request",
        error_code: str = "BAD_REQUEST",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, status_code=400, error_code=error_code, details=details)


class BusinessRuleException(CustomAPIException):
    """A request is well-formed but violates a domain/business rule."""

    def __init__(
        self,
        message: str = "Business rule violation",
        rule: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        details = dict(details or {})
        if rule:
            details["rule"] = rule
        super().__init__(message=message, status_code=400, error_code="BUSINESS_RULE_ERROR", details=details)


# Back-compat alias used by some routes.
BusinessRuleError = BusinessRuleException


# ──────────────────────────────────────────────────────────────────────────
# 401 — Authentication
# ──────────────────────────────────────────────────────────────────────────

class AuthenticationException(CustomAPIException):
    """Caller could not be authenticated at all (missing/invalid/expired token)."""

    def __init__(
        self,
        message: str = "Authentication failed",
        error_code: str = "AUTHENTICATION_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, status_code=401, error_code=error_code, details=details)


UnauthorizedError = AuthenticationException


class TokenRevokedError(AuthenticationException):
    def __init__(self, message: str = "Token has been revoked.", details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, error_code="REVOKED_TOKEN", details=details)


class TokenExpiredError(AuthenticationException):
    def __init__(self, message: str = "Token has expired.", details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, error_code="TOKEN_EXPIRED", details=details)


class InvalidCredentialsError(AuthenticationException):
    def __init__(
        self,
        message: str = "Invalid email or password.",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, error_code="INVALID_CREDENTIALS", details=details)


# ──────────────────────────────────────────────────────────────────────────
# 403 — Authorization
# ──────────────────────────────────────────────────────────────────────────

class AuthorizationException(CustomAPIException):
    """Caller is authenticated but not permitted to perform this action."""

    def __init__(
        self,
        message: str = "Insufficient permissions",
        error_code: str = "AUTHORIZATION_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, status_code=403, error_code=error_code, details=details)


ForbiddenError = AuthorizationException


class AccountInactiveError(AuthorizationException):
    """Account exists but is not (yet, or no longer) active."""

    def __init__(
        self,
        message: str = "Your account is not active.",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, error_code="ACCOUNT_INACTIVE", details=details)


class AccountSuspendedError(AuthorizationException):
    def __init__(
        self,
        message: str = "Account suspended. Contact support.",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, error_code="ACCOUNT_SUSPENDED", details=details)


class EmailNotVerifiedError(AuthorizationException):
    def __init__(
        self,
        message: str = "Please verify your email before signing in.",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, error_code="EMAIL_NOT_VERIFIED", details=details)


class OrganizationLimitError(AuthorizationException):
    """Tenant has hit a plan-enforced limit (seats, storage, etc.)."""

    def __init__(
        self,
        message: str = "Organization limit reached.",
        limit_type: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        details = dict(details or {})
        if limit_type:
            details["limit_type"] = limit_type
        super().__init__(message=message, error_code="ORGANIZATION_LIMIT_REACHED", details=details)


# ──────────────────────────────────────────────────────────────────────────
# 404 — Not Found
# ──────────────────────────────────────────────────────────────────────────

class ResourceNotFoundException(CustomAPIException):
    def __init__(
        self,
        resource: str = "Resource",
        resource_id: Optional[Any] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        message = f"{resource} not found"
        details = dict(details or {})
        if resource_id is not None:
            message = f"{resource} with ID {resource_id} not found"
            details.setdefault("resource", resource)
            details.setdefault("resource_id", resource_id)
        super().__init__(message=message, status_code=404, error_code="RESOURCE_NOT_FOUND", details=details)


NotFoundError = ResourceNotFoundException


# ──────────────────────────────────────────────────────────────────────────
# 409 — Conflict
# ──────────────────────────────────────────────────────────────────────────

# class ConflictError(CustomAPIException):
#     """A uniqueness/state conflict — duplicate email, username, phone, etc."""

#     def __init__(
#         self,
#         message: str = "A conflicting resource already exists.",
#         field: Optional[str] = None,
#         details: Optional[Dict[str, Any]] = None,
#     ):
#         details = dict(details or {})
#         if field:
#             details["field"] = field
#         super().__init__(message=message, status_code=409, error_code="CONFLICT", details=details)

class ConflictError(CustomAPIException):
    """A uniqueness/state conflict — duplicate email, username, phone, etc."""

    def __init__(
        self,
        message: str = "A conflicting resource already exists.",
        field: Optional[str] = None,
        error_code: str = "CONFLICT",  # <-- now overridable
        details: Optional[Dict[str, Any]] = None,
    ):
        details = dict(details or {})
        if field:
            details["field"] = field
        super().__init__(message=message, status_code=409, error_code=error_code, details=details)

class DuplicateResourceException(ConflictError):
    """Back-compat alias for older call sites."""
    pass


# ──────────────────────────────────────────────────────────────────────────
# 422 — Validation
# ──────────────────────────────────────────────────────────────────────────

class ValidationException(CustomAPIException):
    def __init__(
        self,
        message: str = "Validation failed",
        field_errors: Optional[Dict[str, List[str]]] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        details = dict(details or {})
        if field_errors:
            details["field_errors"] = field_errors
        super().__init__(message=message, status_code=422, error_code="VALIDATION_ERROR", details=details)


ValidationError = ValidationException


# ──────────────────────────────────────────────────────────────────────────
# 429 — Rate limiting
# ──────────────────────────────────────────────────────────────────────────

class RateLimitExceededError(CustomAPIException):
    def __init__(
        self,
        message: str = "Too many requests. Please try again later.",
        retry_after_seconds: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        details = dict(details or {})
        if retry_after_seconds is not None:
            details["retry_after_seconds"] = retry_after_seconds
        super().__init__(message=message, status_code=429, error_code="RATE_LIMITED", details=details)


# ──────────────────────────────────────────────────────────────────────────
# 502/503 — Upstream / infra
# ──────────────────────────────────────────────────────────────────────────

class ExternalServiceException(CustomAPIException):
    def __init__(
        self,
        service: str,
        message: str = "External service error",
        details: Optional[Dict[str, Any]] = None,
    ):
        details = dict(details or {})
        details["service"] = service
        super().__init__(message=message, status_code=502, error_code="EXTERNAL_SERVICE_ERROR", details=details)


class ServiceUnavailableError(CustomAPIException):
    """A required internal dependency (e.g. Redis) is unreachable."""

    def __init__(
        self,
        message: str = "Service temporarily unavailable. Please try again.",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, status_code=503, error_code="SERVICE_UNAVAILABLE", details=details)


class EmailServiceError(CustomAPIException):
    """Email provider (Resend, SMTP, SendGrid, etc.) rejected or failed to send."""

    def __init__(
        self,
        message: str = "Failed to send email. Please try again.",
        provider: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        details = dict(details or {})
        if provider:
            details["provider"] = provider
        super().__init__(message=message, status_code=503, error_code="EMAIL_SERVICE_ERROR", details=details)

__all__ = [
    "CustomAPIException",
    "BadRequestError",
    "BusinessRuleException",
    "BusinessRuleError",
    "AuthenticationException",
    "UnauthorizedError",
    "TokenRevokedError",
    "TokenExpiredError",
    "InvalidCredentialsError",
    "AuthorizationException",
    "ForbiddenError",
    "AccountInactiveError",
    "AccountSuspendedError",
    "EmailNotVerifiedError",
    "OrganizationLimitError",
    "ResourceNotFoundException",
    "NotFoundError",
    "ConflictError",
    "DuplicateResourceException",
    "ValidationException",
    "ValidationError",
    "RateLimitExceededError",
    "ExternalServiceException",
    "ServiceUnavailableError",
    "EmailServiceError"
]

