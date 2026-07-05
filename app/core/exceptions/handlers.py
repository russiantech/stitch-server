"""
app/core/exceptions/handlers.py — registers global FastAPI exception handlers.

Import `setup_exception_handlers(app)` once in main.py, after the app is
constructed (this is the name main.py and app/core/exceptions/__init__.py
actually import — keep it stable; renaming it again will reproduce the
same ImportError this file was just fixed for).

Kept separate from custom_exceptions.py so that module has zero
dependency on FastAPI/Starlette/SQLAlchemy and stays trivially
unit-testable on its own.

Every response — success or error — eventually round-trips through
JSONResponse with the same envelope shape: {success, message, error_code,
details, error_id, request_id}. error_id is always present on errors so
a user-reported issue can be grepped straight out of server logs;
request_id is only present when the client sent x-request-id/x-trace-id.
"""

import logging
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

try:
    from sqlalchemy.exc import IntegrityError, ProgrammingError, SQLAlchemyError
    _HAS_SQLALCHEMY = True
except ImportError:  # pragma: no cover - SQLAlchemy is a hard dependency in practice
    _HAS_SQLALCHEMY = False

from app.core.exceptions.custom_exceptions import CustomAPIException

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────

def _error_id() -> str:
    return f"err-{uuid.uuid4().hex[:12]}"


def _request_id(request: Request) -> Optional[str]:
    return request.headers.get("x-request-id") or request.headers.get("x-trace-id")


def _error_response(
    status_code: int,
    message: str,
    *,
    error_code: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    error_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> JSONResponse:
    content: Dict[str, Any] = {
        "success": False,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if error_code:
        content["error_code"] = error_code
    if details:
        content["details"] = details
    if error_id:
        content["error_id"] = error_id
    if request_id:
        content["request_id"] = request_id
    return JSONResponse(status_code=status_code, content=content)


def _log_warn(exc: Exception, request: Request, eid: str, status_code: int) -> None:
    logger.warning(
        "[%s] %s %s — %s (status=%d)",
        eid, request.method, request.url.path, type(exc).__name__, status_code,
    )


def _log_err(exc: Exception, request: Request, eid: str, status_code: int) -> None:
    logger.error(
        "[%s] %s %s — %s (status=%d)\n%s",
        eid, request.method, request.url.path, type(exc).__name__, status_code,
        traceback.format_exc(),
        exc_info=True,
    )


# logger.error(
#     f"[{err_id}] {request.method} {request.url.path} — {exc.__class__.__name__}: {exc}",
#     exc_info=True,
# )

_VALIDATION_FRIENDLY_MESSAGES = {
    "email": "Please enter a valid email address.",
    "phone": "Invalid phone number format.",
    "password": "Password must be at least 8 characters.",
    "names": "Name must be 2–100 characters.",
    "username": "Username must be 3–30 characters (letters, numbers, underscores).",
}

_INTEGRITY_VIOLATION_MESSAGES = {
    "UniqueViolation": "A record with this value already exists.",
    "ForeignKeyViolation": "Referenced record does not exist.",
    "NotNullViolation": "Required field cannot be empty.",
}


def _status_to_error_code(status_code: int) -> str:
    return {
        400: "BAD_REQUEST",
        401: "AUTHENTICATION_ERROR",
        403: "AUTHORIZATION_ERROR",
        404: "RESOURCE_NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        502: "EXTERNAL_SERVICE_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }.get(status_code, f"HTTP_{status_code}")


# ─────────────────────────────────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────────────────────────────────

def setup_exception_handlers(app: FastAPI) -> None:
    """Registers every handler below on `app`. Call exactly once, in
    main.py's create_app(), after the FastAPI instance is constructed.
    """

    @app.exception_handler(CustomAPIException)
    async def custom_api_exception_handler(request: Request, exc: CustomAPIException):
        eid = _error_id()
        # 5xx raised deliberately (e.g. ServiceUnavailableError when Redis
        # is down) are still unexpected from an ops standpoint — log at
        # error level with a correlation id; 4xx are routine and only
        # warrant a warning.
        if exc.status_code >= 500:
            _log_err(exc, request, eid, exc.status_code)
        else:
            _log_warn(exc, request, eid, exc.status_code)
        return _error_response(
            exc.status_code,
            exc.message,
            error_code=exc.error_code,
            details=exc.details,
            error_id=eid,
            request_id=_request_id(request),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Pydantic/FastAPI request validation errors → uniform shape.

        Fires for malformed JSON bodies, missing required fields, wrong
        types, etc. — validation that happens *before* a route function
        ever runs, so it bypasses our own ValidationException. Normalized
        to the same envelope here, with a user-friendly top-level message
        derived from the first failing field plus the full field-by-field
        breakdown preserved in `details.field_errors` for the frontend to
        render inline.
        """
        eid = _error_id()
        _log_warn(exc, request, eid, 422)

        errors = exc.errors()
        field_errors: Dict[str, list] = {}
        for err in errors:
            loc = err.get("loc", ())
            field = ".".join(str(p) for p in loc[1:]) if len(loc) > 1 else str(loc[-1] if loc else "request")
            field_errors.setdefault(field, []).append(err.get("msg", "Invalid value"))

        first = errors[0] if errors else {}
        first_field = str(first.get("loc", ["request"])[-1])
        message = _VALIDATION_FRIENDLY_MESSAGES.get(first_field, first.get("msg", "Validation failed"))

        return _error_response(
            422,
            message,
            error_code="VALIDATION_ERROR",
            details={"field_errors": field_errors},
            error_id=eid,
            request_id=_request_id(request),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """Catches plain `raise HTTPException(...)` calls left in legacy
        code so even routes that haven't been migrated to
        CustomAPIException subclasses still return the standard envelope.
        """
        eid = _error_id()
        if exc.status_code >= 500:
            _log_err(exc, request, eid, exc.status_code)
        else:
            _log_warn(exc, request, eid, exc.status_code)

        detail = exc.detail
        message = detail if isinstance(detail, str) else "Request failed"
        details = detail if isinstance(detail, dict) else {}
        return _error_response(
            exc.status_code,
            message,
            error_code=_status_to_error_code(exc.status_code),
            details=details,
            error_id=eid,
            request_id=_request_id(request),
        )

    if _HAS_SQLALCHEMY:

                # In handlers.py, replace the integrity_error_handler:
        """
        Fix 1: Parse the Postgres error detail in the IntegrityError handler
        Update handlers.py to extract the field name from the psycopg2 error message: 
        """
        @app.exception_handler(IntegrityError)
        async def integrity_error_handler(request: Request, exc: IntegrityError):
            eid = _error_id()
            _log_err(exc, request, eid, 409)
            
            orig = getattr(exc, "orig", None)
            violation = type(orig).__name__ if orig else "UNKNOWN"
            
            # Extract field info from the Postgres error message
            detail = getattr(orig, "diag", None)
            message = _INTEGRITY_VIOLATION_MESSAGES.get(violation, "Database constraint violated.")
            field_errors = {}
            
            # Parse the constraint violation detail for user-friendly feedback
            if detail and hasattr(detail, "message_detail") and detail.message_detail:
                pg_detail = detail.message_detail
                # Example: "Key (email)=(chris@example.com) already exists."
                import re
                match = re.search(r"Key \(([^)]+)\)=\(([^)]+)\)", pg_detail)
                if match:
                    field_name, field_value = match.group(1), match.group(2)
                    field_errors[field_name] = [f"A record with this {field_name} ({field_value}) already exists."]
                    message = f"A record with this {field_name} already exists for {field_value}."
            
            return _error_response(
                409,
                message,
                error_code="INTEGRITY_ERROR",
                details={
                    "violation_type": violation,
                    **({"field_errors": field_errors} if field_errors else {}),
                },
                error_id=eid,
                request_id=_request_id(request),
            )
            
        # @app.exception_handler(IntegrityError)
        # async def integrity_error_handler(request: Request, exc: IntegrityError):
        #     """Catches uniqueness/FK/not-null violations that slip past
        #     application-level uniqueness checks (e.g. a genuine race
        #     condition between the pre-check and the INSERT/UPDATE).
        #     Application code should still do its own pre-checks for a
        #     good error message — this is the safety net underneath that,
        #     not a replacement for it.
        #     """
        #     eid = _error_id()
        #     _log_err(exc, request, eid, 409)
        #     orig = getattr(exc, "orig", None)
        #     violation = type(orig).__name__ if orig else "UNKNOWN"
        #     return _error_response(
        #         409,
        #         _INTEGRITY_VIOLATION_MESSAGES.get(violation, "Database constraint violated."),
        #         error_code="INTEGRITY_ERROR",
        #         details={"violation_type": violation},
        #         error_id=eid,
        #         request_id=_request_id(request),
        #     )

        @app.exception_handler(ProgrammingError)
        async def programming_error_handler(request: Request, exc: ProgrammingError):
            """Schema mismatch — missing table/column, usually a forgotten
            migration. Always a 500 and always an ops problem, never a
            client-facing detail to expose.
            """
            eid = _error_id()
            _log_err(exc, request, eid, 500)
            return _error_response(
                500,
                "A database schema error occurred. Please contact support.",
                error_code="SCHEMA_ERROR",
                error_id=eid,
                request_id=_request_id(request),
            )

        @app.exception_handler(SQLAlchemyError)
        async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError):
            """Catch-all for any other SQLAlchemy error not covered above
            (connection drops, timeouts, etc.) — must come after the more
            specific IntegrityError/ProgrammingError handlers since those
            are subclasses of this.
            """
            eid = _error_id()
            _log_err(exc, request, eid, 500)
            return _error_response(
                500,
                "A database error occurred. Please try again.",
                error_code="DATABASE_ERROR",
                error_id=eid,
                request_id=_request_id(request),
            )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        """A bare `raise ValueError(...)` left in service/util code (e.g.
        from int()/Decimal() parsing, enum coercion) — treated as a 400
        rather than falling through to the generic 500 handler, since a
        ValueError almost always means "the input was bad," not "the
        server broke."
        """
        eid = _error_id()
        _log_warn(exc, request, eid, 400)
        return _error_response(
            400,
            str(exc) or "Invalid value.",
            error_code="INVALID_VALUE",
            error_id=eid,
            request_id=_request_id(request),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """Last-resort catch-all. Never leak stack traces or raw exception
        text to clients — log the full traceback server-side under a
        correlation id and return a generic message instead.
        """
        eid = _error_id()
        _log_err(exc, request, eid, 500)
        return _error_response(
            500,
            "An unexpected error occurred. Please try again or contact support.",
            error_code="INTERNAL_ERROR",
            error_id=eid,
            request_id=_request_id(request),
        )

    registered = 6 + (3 if _HAS_SQLALCHEMY else 0)
    logger.info("Registered %d exception handlers", registered)


# Back-compat alias: the earlier draft of this module (the one this file
# replaces) used this name. Kept so nothing importing it directly breaks;
# main.py and app/core/exceptions/__init__.py should use
# setup_exception_handlers going forward.
register_exception_handlers = setup_exception_handlers

__all__ = ["setup_exception_handlers", "register_exception_handlers"]

