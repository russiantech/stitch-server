# # """
# # app/api/v1/auth.py — Authentication endpoints (Stitch, multi-tenant)
# # =====================================================================

# # Tenancy model
# # -------------

# v3
"""
app/api/v1/auth.py — Authentication endpoints (Stitch, multi-tenant)
=====================================================================

Tenancy model
-------------
Stitch is multi-tenant. Every User belongs to exactly one Organization
(except a super_admin, who is platform-level and may be org_id=None).
The *first* account ever created on a fresh deployment becomes that
organization's owning admin. After that, new accounts are either:

  (a) created directly by an existing org admin (POST /users — see
      users.py), or
  (b) self-signed-up by the public, IF the org has enabled
      `allow_public_signup` — in which case the new account is created
      INACTIVE and requires admin approval (PUT /users/{id}).

Redis-staged signup
--------------------
No account is ever written to Postgres before its email is verified.
The flow is:

    POST /auth/signup          → validates input, stages payload in Redis
                                  under a random opaque token, emails a
                                  6-digit code, returns the token.
    POST /auth/signup/verify   → looks up the staged payload by token,
                                  checks the code, and ONLY THEN creates
                                  the User (+ Organization, if this is
                                  the first account) row in Postgres.
    POST /auth/signup/resend   → reuses the same staged payload, issues
                                  a fresh code, resets the Redis TTL.

This means: an abandoned signup leaves no row in the users table, ever;
duplicate concurrent signups for the same email are naturally
serialized by the final uniqueness check at verify-time; and the
"is this the first account" decision can't be poisoned by an
unverified, never-completed signup attempt.

Redis usage here is built directly on app/services/redis_service.py's
module-level helpers (rset/rget/rdel/rexists/rttl + the OTP/blacklist/
session conveniences already defined there) — no separate client class,
no DI wrapper. That module already degrades to logged no-ops if Redis
itself errors; routes here additionally treat "nothing came back when
something was expected" as a clean, typed 4xx (session expired / service
unavailable) rather than letting a None propagate into a 500.

Response conventions
--------------------
Every route uses api_response() directly so the call sites are
self-documenting — the success flag, message, and data are always
visible at the call site rather than inferred from a helper's name.
The 201 / 202 status codes that differ from the 200 default are still
explicit via the status_code kwarg.
"""

import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from app.enums.stitch import UserStatus
from sqlalchemy.orm import Session

from app.api.deps.users import get_db, get_current_user, admin_required as require_admin
from app.core.security.auth import (
    create_access_token,
    create_refresh_token,
    create_impersonation_token,
    decode_token,
)
from app.core.security.auth import hash_password, verify_password
from app.core.exceptions.custom_exceptions import (
    BadRequestError,
    ConflictError,
    CustomAPIException,
    ForbiddenError,
    NotFoundError,
    OrganizationLimitError,
    RateLimitExceededError,
    ServiceUnavailableError,
    ValidationException,
)
from app.models.users import User
from app.models.organization import Organization
from app.schemas.auth import (
    SigninSchema,
    ChangePasswordSchema,
    SignupSchema,
    SignupVerifySchema,
    ForgotPasswordSchema,
    ResetPasswordSchema,
)
from app.services.auth_service import authenticate_user, create_user
from app.services.email_service import (
    send_otp,
    send_welcome
    )
from app.services.redis_service import (
    rset, rget, rdel, rexists, rttl,
    blacklist_token, is_token_blacklisted,
)
from app.utils.responses import api_response
from app.utils.helpers import get_client_ip, generate_code

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])

# ── Tunables ────────────────────────────────────────────────────────────
SIGNUP_TOKEN_TTL_SECONDS = 600          # 10 min to enter the email code
PASSWORD_RESET_TTL_SECONDS = 900        # 15 min to complete a reset
REFRESH_BLACKLIST_TTL_SECONDS = 86400 * 7
DEFAULT_FREE_TIER_MAX_USERS = 5

LOGIN_ATTEMPT_WINDOW_SECONDS = 900      # 15 min rolling window
LOGIN_ATTEMPT_MAX = 100                 # per identifier, per window
OTP_RESEND_WINDOW_SECONDS = 60          # min gap between resends

# Key namespaces — kept local to this module (vs. baked into redis_service)
# since they're auth-flow-specific staging keys, not generic primitives.
SIGNUP_PENDING_PREFIX = "stitch:signup_pending:"
SIGNUP_EMAIL_INDEX_PREFIX = "stitch:signup_email_index:"
SIGNUP_RESEND_THROTTLE_PREFIX = "stitch:signup_resend_throttle:"
PWD_RESET_PREFIX = "stitch:pwd_reset:"
PWD_RESET_RESEND_THROTTLE_PREFIX = "stitch:pwd_reset_resend_throttle:"
LOGIN_ATTEMPTS_PREFIX = "stitch:login_attempts:"


# ─────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────

def _is_super_admin(user: User) -> bool:
    return any(getattr(r, "name", None) == "super_admin" for r in (user.roles or []))


def _check_email_uniqueness(db: Session, email: str, exclude_user_id: Optional[str] = None) -> None:
    q = db.query(User).filter(User.email == email, User.deleted == False)  # noqa: E712
    if exclude_user_id:
        q = q.filter(User.id != exclude_user_id)
    if q.first():
        raise ConflictError(f"An account with this email[{email}] already exists. Consider signing in instead.", field="email")


def _check_username_uniqueness(db: Session, username: str, exclude_user_id: Optional[str] = None) -> None:
    q = db.query(User).filter(User.username == username, User.deleted == False)  # noqa: E712
    if exclude_user_id:
        q = q.filter(User.id != exclude_user_id)
    if q.first():
        raise ConflictError(f"An account with this username[{username}] already exists. Consider signing in instead.", field="username")


def _check_phone_uniqueness(db: Session, phone: Optional[str]) -> None:
    if not phone:
        return
    if db.query(User).filter(User.phone == phone, User.deleted == False).first():  # noqa: E712
        raise ConflictError(f"An account with this phone number[{phone}] already exists. Consider signing in instead.", field="phone")


# def _incr_with_window(key: str, window_seconds: int) -> int:
#     """Approximate atomic increment for rate-limiting counters.
#     Composed from rget/rset because redis_service has no INCR wrapper.
#     Not perfectly race-free under extreme concurrency — acceptable for a
#     soft throttle that doesn't need to be a hard security boundary.
#     If stricter correctness is ever needed, add a true rincr() using the
#     underlying client's INCR/EXPIRE pipeline in redis_service.py.
#     """
#     current = rget(key)
#     count = int(current) + 1 if current is not None else 1
#     if current is None:
#         rset(key, count, ttl=window_seconds)
#     else:
#         rset(key, count) # preserve existing TTL — don't reset the window
#     return count


def _incr_with_window(key: str, window_seconds: int) -> int:
    """Atomic increment with preserved window. Uses Redis INCR."""
    try:
        from app.services.redis_service import rincr
        return rincr(key)
    except ImportError:
        # Fallback (should never hit if rincr is in same module)
        current = rget(key)
        count = int(current) + 1 if current is not None else 1
        if current is None:
            rset(key, count, ttl=window_seconds)
        else:
            rset(key, count)  # preserve existing TTL
        return count

def _token_pair(user: User) -> dict:
    extra = {
        "roles": user.role_names,
        "org_id": str(user.organization_id) if user.organization_id else None,
    }
    return {
        "access_token": create_access_token(subject=str(user.id), extra=extra),
        "refresh_token": create_refresh_token(subject=str(user.id)),
        "token_type": "Bearer",
        "user": user.get_summary(),
    }


def _clear_signup_staging(token: str, email: str) -> None:
    rdel(f"{SIGNUP_PENDING_PREFIX}{token}", f"{SIGNUP_EMAIL_INDEX_PREFIX}{email}")


# ─────────────────────────────────────────────────────────────────────────
# Step 1: Initiate signup
# ─────────────────────────────────────────────────────────────────────────


@router.post(
    "/signup",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Step 1: Initiate signup (first org admin, or public signup if org allows it)",
)
async def signup(
    data: SignupSchema,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Stages the signup in Redis and emails a 6-digit verification code.
    No row is written to Postgres at this stage — see module docstring.

    RULES
    -----
    - If NO active users exist anywhere → this becomes the platform's
      first organization + its owning admin (no auth required).
    - Otherwise, public signup is only permitted if exactly one
      Organization exists AND that org has `allow_public_signup = True`.
    - New public signups are created INACTIVE pending admin approval —
      enforced again at verify-time, not just here.
    """
    email = data.email.lower().strip()
    username = data.username.lower().strip()

    # EDGE: don't leak whether *Postgres* already has this account vs. it
    # being mid-flight in Redis — both cases should read as "in use."
    _check_email_uniqueness(db, email)
    _check_username_uniqueness(db, username)
    _check_phone_uniqueness(db, data.phone)

    user_count = db.query(User).filter(User.deleted == False).count()  # noqa: E712
    is_first_account = user_count == 0
    org_code = (data.org_code or "").strip().upper() or None

    if is_first_account and not org_code:
        # ── Path A: Very first account on this deployment ─────────────────
        # Creates a new organization. org_name from payload or derived from username.
        is_public_signup = False
        target_org_id = None

    elif org_code:
        # ── Path B: Joining an existing org via invite code ────────────────
        org = (
            db.query(Organization)
            .filter(Organization.invite_code == org_code, Organization.deleted == False)  # noqa: E712
            .first()
        )
        if not org:
            raise BadRequestError(
                f"No organization found with code '{org_code}'. Check the code and try again.",
                error_code="INVALID_ORG_CODE",
            )
        if not org.is_active or org.is_paused:
            raise ForbiddenError(
                "This organization is not currently accepting new members.",
                error_code="ORG_UNAVAILABLE",
            )
        if not org.allow_public_signup:
            raise ForbiddenError(
                "This organization requires an admin invitation to join.",
                error_code="ORG_INVITE_ONLY",
            )
        is_public_signup = True
        target_org_id = str(org.id)

    else:
        # ── Path C: No org_code, not first account ─────────────────────────
        # Could be a new tenant wanting to create their own org.
        # We allow this — Stitch is multi-tenant, multiple orgs are the point.
        is_public_signup = False
        target_org_id = None

    # EDGE: a duplicate signup attempt for an email that's already staged
    # (but not yet verified) should refresh-and-resend rather than create
    # a second, divergent staged payload under a different token.
    existing_token = rget(f"{SIGNUP_EMAIL_INDEX_PREFIX}{email}")
    if existing_token and rexists(f"{SIGNUP_PENDING_PREFIX}{existing_token}"):
        return await _reissue_signup_code(background_tasks, str(existing_token))

    email_code = generate_code(6)
    signup_token = secrets.token_urlsafe(32)

    signup_data = {
        "username": username,
        "email": email,
        "names": data.names or username,
        "phone": data.phone or "",
        "password_hash": hash_password(data.password),
        "email_code": email_code,
        "attempts": 0,
        "is_org_admin": not is_public_signup,
        "is_public_signup": is_public_signup,
        "organization_id": target_org_id,
        "org_name": data.org_name or f"{username}'s Organization",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ip": get_client_ip(request),
    }

    logger.debug("Staging signup data %s", signup_data, extra={"email": email})

    if not rset(f"{SIGNUP_PENDING_PREFIX}{signup_token}", signup_data, ttl=SIGNUP_TOKEN_TTL_SECONDS):
        raise ServiceUnavailableError("Could not initiate signup. Please try again.")
    rset(f"{SIGNUP_EMAIL_INDEX_PREFIX}{email}", signup_token, ttl=SIGNUP_TOKEN_TTL_SECONDS)

    # if not send_verification_email(email, signup_data["names"], email_code):
    if not send_otp(email, signup_data["names"], email_code):
        # EDGE: never leave an orphaned staged signup if the email never
        # went out — otherwise the user is locked out of retrying with
        # the same email until TTL expiry.
        rdel(f"{SIGNUP_PENDING_PREFIX}{signup_token}", f"{SIGNUP_EMAIL_INDEX_PREFIX}{email}")
        raise ServiceUnavailableError(
            f"Failed to send verification email. Please check the address [{email}] and try again."
        )

    logger.info("Signup initiated for %s (first_account=%s)", email, is_first_account)

    return api_response(
        success=True,
        message="Verification code sent! Check your email.",
        data={"token": signup_token, "email": email, "expires_in_seconds": SIGNUP_TOKEN_TTL_SECONDS},
        status_code=202,
    )


async def _reissue_signup_code(background_tasks: BackgroundTasks, token: str):
    signup_data = rget(f"{SIGNUP_PENDING_PREFIX}{token}")
    if not signup_data:
        raise ServiceUnavailableError("Could not initiate signup. Please try again.")
    new_code = generate_code(6)
    signup_data["email_code"] = new_code
    signup_data["attempts"] = 0
    rset(f"{SIGNUP_PENDING_PREFIX}{token}", signup_data, ttl=SIGNUP_TOKEN_TTL_SECONDS)
    background_tasks.add_task(
        send_otp, signup_data["email"], signup_data["names"], new_code
    )
    return api_response(
        True,
        "Verification code sent! Check your email.",
        data={"token": token, "email": signup_data["email"], "expires_in_seconds": SIGNUP_TOKEN_TTL_SECONDS},
        status_code=202,
    )


# ─────────────────────────────────────────────────────────────────────────
# Step 2: Verify code → create account
# ─────────────────────────────────────────────────────────────────────────

@router.post(
    "/signup/verify",
    status_code=status.HTTP_201_CREATED,
    summary="Step 2: Verify code and create account",
)
async def signup_verify(
    data: SignupVerifySchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if not data.token or not data.email_code:
        raise ValidationException(
            "Token and verification code are required.",
            field_errors={
                **({"token": ["Required"]} if not data.token else {}),
                **({"email_code": ["Required"]} if not data.email_code else {}),
            },
        )

    pending_key = f"{SIGNUP_PENDING_PREFIX}{data.token}"
    signup_data = rget(pending_key)
    if not signup_data:
        raise BadRequestError(
            "Session expired or invalid. Please start again.",
            error_code="SIGNUP_SESSION_EXPIRED",
        )

    # EDGE: cap verification attempts so a leaked/guessed token can't be
    # brute-forced against a 6-digit code indefinitely within the TTL.
    attempts = int(signup_data.get("attempts", 0))
    if attempts >= 5:
        rdel(pending_key)
        raise BadRequestError(
            "Too many incorrect attempts. Please start signup again.",
            error_code="SIGNUP_SESSION_EXPIRED",
        )

    submitted_code = data.email_code.strip().upper()
    if signup_data.get("email_code") != submitted_code:
        signup_data["attempts"] = attempts + 1
        # Preserve remaining TTL — don't reset the window on a wrong guess.
        remaining_ttl = rttl(pending_key)
        rset(
            pending_key,
            signup_data,
            ttl=remaining_ttl if remaining_ttl and remaining_ttl > 0 else SIGNUP_TOKEN_TTL_SECONDS,
        )
        raise BadRequestError("Invalid verification code.", error_code="INVALID_OTP")

    email = signup_data["email"]
    username = signup_data["username"]

    # EDGE: re-check uniqueness at verify-time, not just initiate-time —
    # another signup (or admin-created account) for the same email/
    # username could have completed in the meantime.
    _check_email_uniqueness(db, email)
    _check_username_uniqueness(db, username)

    if signup_data.get("is_public_signup"):
        org = db.query(Organization).filter(Organization.id == signup_data["organization_id"]).first()
        if not org:
            rdel(pending_key)
            raise NotFoundError("Organization", signup_data.get("organization_id"))

        current_user_count = db.query(User).filter(
            User.organization_id == org.id, User.deleted == False  # noqa: E712
        ).count()
        max_users = org.max_users if org.max_users is not None else DEFAULT_FREE_TIER_MAX_USERS
        if current_user_count >= max_users:
            rdel(pending_key)
            raise OrganizationLimitError(
                "This organization has reached its user limit. Ask an administrator to upgrade the plan.",
                limit_type="max_users",
            )

        user = create_user(
            db=db,
            username=username,
            email=email,
            password_hash=signup_data["password_hash"],
            names=signup_data["names"],
            phone=signup_data["phone"] or None,
            organization_id=org.id,
            is_org_admin=False,
            email_verified=True,
        )
        user.is_active = False  # pending admin approval
        user.ip = signup_data.get("ip")
        db.commit()
        db.refresh(user)

        _clear_signup_staging(data.token, email)
        background_tasks.add_task(send_welcome, user.email, user.names or user.username)

        logger.info(
            "Public signup verified: '%s' created in org '%s', pending activation",
            user.username, org.name,
        )
        return api_response(
            True,
            "Account created! An administrator must activate your account before you can sign in.",
            data={"user": user.get_summary(), "organization": {"id": org.id, "name": org.name}},
            status_code=201,
        )

    # # ── First account on this deployment: create Organization + admin ──
    # org = Organization(
    #     name=signup_data.get("org_name") or "Default Organization",
    #     slug=username,
    #     plan="free",
    #     allow_public_signup=False,
    #     max_users=DEFAULT_FREE_TIER_MAX_USERS,
    #     created_at=datetime.now(timezone.utc),
    # )
    # db.add(org)
    # db.flush()  # get org.id without committing yet — keeps org+user atomic
    
    # v2
    from app.utils.helpers import make_slug

    # ── First account on this deployment: create Organization + admin ──
    org_name = signup_data.get("org_name") or "Default Organization"
    org_slug = make_slug(org_name, suffix=True)

    org = Organization(
        name=org_name,
        slug=org_slug,
        plan="free",
        allow_public_signup=False,
        max_users=DEFAULT_FREE_TIER_MAX_USERS,
        created_at=datetime.now(timezone.utc),
    )
    db.add(org)
    db.flush()

    user = create_user(
        db=db,
        username=username,
        email=email,
        password_hash=signup_data["password_hash"],
        names=signup_data["names"],
        phone=signup_data["phone"] or None,
        organization_id=org.id,
        is_org_admin=True,
        email_verified=True,
    )
    # First account must be able to sign in immediately — there's no
    # other admin yet to approve it.
    # user.is_active = True
    user.status = UserStatus.ACTIVE
    user.ip = signup_data.get("ip")
    db.flush()

    org.owner_id = user.id
    db.commit()
    db.refresh(user)
    db.refresh(org)

    _clear_signup_staging(data.token, email)

    access_token = create_access_token(
        subject=str(user.id),
        extra={"roles": user.role_names, "org_id": str(org.id)},
    )

    refresh_token = create_refresh_token(subject=str(user.id))

    background_tasks.add_task(send_welcome, user.email, user.names or user.username)
    logger.info("Organization '%s' created by '%s' (first account)", org.name, user.username)

    return api_response(
        True,
        "Account created successfully! Welcome to Stitch.",
        data={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "user": user.get_summary(),
            "organization": {"id": org.id, "name": org.name, "plan": org.plan},
        },
        status_code=201,
    )


@router.post("/signup/resend", summary="Resend signup verification code")
async def resend_signup_code(
    data: dict,
    background_tasks: BackgroundTasks,
):
    token = (data or {}).get("token", "")
    if not token:
        raise ValidationException("Token is required.", field_errors={"token": ["Required"]})

    # EDGE: throttle resend spam independent of the 10-min staging TTL.
    throttle_key = f"{SIGNUP_RESEND_THROTTLE_PREFIX}{token}"
    if rexists(throttle_key):
        raise RateLimitExceededError(
            "Please wait before requesting another code.",
            retry_after_seconds=OTP_RESEND_WINDOW_SECONDS,
        )
    rset(throttle_key, "1", ttl=OTP_RESEND_WINDOW_SECONDS)

    return await _reissue_signup_code(background_tasks, token)


# ─────────────────────────────────────────────────────────────────────────
# Admin config: toggle public signup
# ─────────────────────────────────────────────────────────────────────────

@router.post("/config/signup-toggle", summary="Admin: enable/disable public signup for the org")
async def toggle_public_signup(
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    if not org:
        raise NotFoundError("Organization", current_user.organization_id)

    allow = bool((data or {}).get("allow_public_signup", False))
    org.allow_public_signup = allow
    db.commit()

    logger.info(
        "Admin %s %s public signup for org %s",
        current_user.username, "enabled" if allow else "disabled", org.name,
    )
    return api_response(
        True,
        f"Public signup {'enabled' if allow else 'disabled'}.",
        data={
            "public_signup": "enabled" if allow else "disabled",
            "allow_public_signup": org.allow_public_signup,
        },
    )


# ─────────────────────────────────────────────────────────────────────────
# Sign in
# ─────────────────────────────────────────────────────────────────────────

@router.post("/signin", summary="Sign in with email/username/phone + password")
async def signin(
    data: SigninSchema,
    request: Request,
    db: Session = Depends(get_db),
):
    identifier = (data.identifier or "").strip().lower()

    # EDGE: basic brute-force throttle keyed on the *identifier*, not IP —
    # works behind shared NATs/proxies and doesn't penalize other users
    # of the same network.
    attempt_key = f"{LOGIN_ATTEMPTS_PREFIX}{identifier}"
    attempts = _incr_with_window(attempt_key, LOGIN_ATTEMPT_WINDOW_SECONDS)
    if attempts > LOGIN_ATTEMPT_MAX:
        raise RateLimitExceededError(
            "Too many sign-in attempts. Please try again later.",
            retry_after_seconds=LOGIN_ATTEMPT_WINDOW_SECONDS,
        )

    user = authenticate_user(db, identifier, data.password)
    if not user:
        raise CustomAPIException(
            "Invalid credentials. Please check your identifier and password.",
            status_code=401,
            error_code="INVALID_CREDENTIALS",
        )
    if not user.is_active:
        raise ForbiddenError(
            "Your account is pending activation or has been deactivated. Contact an administrator.",
            error_code="ACCOUNT_INACTIVE",
        )
    if not user.email_verified:
        raise ForbiddenError(
            "Please verify your email before signing in.",
            error_code="EMAIL_NOT_VERIFIED",
        )

    user.is_online = True
    user.last_seen = datetime.now(timezone.utc)
    db.commit()

    # EDGE: clear the throttle counter on success so legitimate users
    # who fat-fingered a password a few times aren't penalized later.
    rdel(attempt_key)

    access_token = create_access_token(
        subject=str(user.id),
        extra={
            "roles": user.role_names,
            "org_id": str(user.organization_id) if user.organization_id else None,
        },
    )
    refresh_token = create_refresh_token(subject=str(user.id))

    return api_response(
        True,
        "Sign in successful. Welcome back!",
        data={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "user": user.get_summary(),
        },
    )


# ─────────────────────────────────────────────────────────────────────────
# Refresh / Me / Signout
# ─────────────────────────────────────────────────────────────────────────

@router.post("/refresh", summary="Exchange refresh token for a new access token")
async def refresh_token_endpoint(
    request: Request,
    db: Session = Depends(get_db),
):
    body = await request.json()
    token = (body or {}).get("refresh_token")
    if not token:
        raise ValidationException(
            "Refresh token required.",
            field_errors={"refresh_token": ["Required"]},
        )

    if is_token_blacklisted(token):
        raise CustomAPIException("Token has been revoked.", status_code=401, error_code="REVOKED_TOKEN")

    payload = decode_token(token)
    if not payload or payload.get("type") != "refresh":
        raise CustomAPIException(
            "Invalid or expired refresh token.",
            status_code=401,
            error_code="INVALID_TOKEN",
        )

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id, User.deleted == False).first()  # noqa: E712
    if not user or not user.is_active:
        raise CustomAPIException(
            "User not found or inactive.",
            status_code=401,
            error_code="USER_NOT_FOUND",
        )

    access_token = create_access_token(
        subject=str(user.id),
        extra={
            "roles": user.role_names,
            "org_id": str(user.organization_id) if user.organization_id else None,
        },
    )
    return api_response(
        True,
        "Token refreshed.",
        data={"access_token": access_token, "token_type": "Bearer"},
    )


@router.get("/me", summary="Get current authenticated user profile")
async def get_me(current_user: User = Depends(get_current_user)):
    org_summary = None
    if current_user.organization_id and current_user.organization:
        org_summary = current_user.organization.get_summary()
    return api_response(
        True,
        "Profile fetched.",
        data={**current_user.get_summary(), "organization": org_summary},
    )


@router.post("/signout", summary="Sign out")
async def signout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # EDGE: blacklist both the access token presented on this call and any
    # refresh token the client sends in the body — covers clients that only
    # have one or the other available at signout time.
    auth_header = request.headers.get("authorization", "")
    bearer = auth_header[7:] if auth_header.lower().startswith("bearer ") else auth_header
    if bearer:
        blacklist_token(bearer, ttl=REFRESH_BLACKLIST_TTL_SECONDS)
    try:
        body = await request.json()
    except Exception:
        body = {}
    refresh = (body or {}).get("refresh_token")
    if refresh:
        blacklist_token(refresh, ttl=REFRESH_BLACKLIST_TTL_SECONDS)

    current_user.is_online = False
    current_user.last_seen = datetime.now(timezone.utc)
    db.commit()

    return api_response(
        True,
        f"Signed out successfully. Goodbye, {current_user.names or current_user.username}!",
    )


# ─────────────────────────────────────────────────────────────────────────
# Password management
# ─────────────────────────────────────────────────────────────────────────

@router.post("/forgot-password", summary="Request a password reset code")
async def forgot_password(
    data: ForgotPasswordSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    email = data.email.lower().strip()

    user = db.query(User).filter(
        User.email == email,
        User.deleted == False,  # noqa: E712
        User.status == UserStatus.ACTIVE,  # noqa: E712
    ).first()

    reset_token = secrets.token_urlsafe(32)
    reset_code = generate_code(6)

    # EDGE: always return the same 200 + token whether or not the email
    # exists, to avoid account enumeration. A bogus token supplied to
    # /reset-password later just resolves to "session expired."
    if user:
        reset_key = f"{PWD_RESET_PREFIX}{reset_token}"
        
        # in forgot_password, add name to the staged reset_key data:
        if not rset(
            reset_key,
            {
                "user_id": str(user.id), 
                "email": user.email, 
                "name": user.names or user.username,
                "reset_code": reset_code, "attempts": 0},
                ttl=PASSWORD_RESET_TTL_SECONDS,
            ):
            raise ServiceUnavailableError("Could not initiate password reset. Please try again.")

        if not send_otp(user.email, user.names or user.username, reset_code, purpose="reset"):
            rdel(reset_key)
            raise ServiceUnavailableError("Failed to send reset email. Please try again.")

        logger.info("Password reset initiated for %s", user.email)

    # # v2
    # if user:
    #     reset_key = f"{PWD_RESET_PREFIX}{reset_token}"
    #     if not rset(
    #         reset_key,
    #         {
    #             "user_id": str(user.id),
    #             "email": user.email,
    #             "name": user.names or user.username,
    #             "reset_code": reset_code,
    #             "attempts": 0,
    #         },
    #         ttl=PASSWORD_RESET_TTL_SECONDS,
    #     ):
    #         raise ServiceUnavailableError("Could not stage password reset. Please try again.")

    #     # This now raises EmailServiceError on any failure — no bool check needed
    #     send_otp(user.email, user.names or user.username, reset_code, purpose="reset")

    #     logger.info("Password reset initiated for %s", user.email)

    return api_response(
        True,
        "If that email is registered, a reset code has been sent.",
        data={"token": reset_token, "email": email, "expires_in_seconds": PASSWORD_RESET_TTL_SECONDS},
    )


@router.post("/forgot-password/verify-code", summary="Verify a reset code without consuming it")
async def verify_reset_code(data: dict):
    token = (data or {}).get("token", "")
    email_code = (data or {}).get("email_code", "").strip().upper()
    if not token or not email_code or len(email_code) != 6:
        raise ValidationException(
            "Token and 6-digit code are required.",
            field_errors={
                **({"token": ["Required"]} if not token else {}),
                **({"email_code": ["Must be 6 digits"]} if not email_code or len(email_code) != 6 else {}),
            },
        )

    reset_key = f"{PWD_RESET_PREFIX}{token}"
    reset_data = rget(reset_key)
    if not reset_data:
        raise BadRequestError("Session expired. Please start again.", error_code="RESET_SESSION_EXPIRED")

    attempts = int(reset_data.get("attempts", 0))
    if attempts >= 5:
        rdel(reset_key)
        raise BadRequestError(
            "Too many incorrect attempts. Please request a new reset code.",
            error_code="RESET_SESSION_EXPIRED",
        )

    if reset_data.get("reset_code") != email_code:
        reset_data["attempts"] = attempts + 1
        remaining_ttl = rttl(reset_key)
        rset(
            reset_key,
            reset_data,
            ttl=remaining_ttl if remaining_ttl and remaining_ttl > 0 else PASSWORD_RESET_TTL_SECONDS,
        )
        raise BadRequestError("Invalid verification code.", error_code="INVALID_OTP")

    return api_response(True, "Code verified.", data={"valid": True})


@router.post("/reset-password", summary="Reset password with verified code")
async def reset_password(
    data: ResetPasswordSchema,
    db: Session = Depends(get_db),
):
    if not data.token or not data.email_code or not data.new_password:
        raise ValidationException(
            "Token, code, and new password are required.",
            field_errors={
                **({"token": ["Required"]} if not data.token else {}),
                **({"email_code": ["Required"]} if not data.email_code else {}),
                **({"new_password": ["Required"]} if not data.new_password else {}),
            },
        )
    if len(data.new_password) < 8:
        raise ValidationException(
            "Password must be at least 8 characters.",
            field_errors={"new_password": ["Must be at least 8 characters"]},
        )

    reset_key = f"{PWD_RESET_PREFIX}{data.token}"
    reset_data = rget(reset_key)
    if not reset_data or reset_data.get("reset_code") != data.email_code.strip().upper():
        raise BadRequestError("Invalid or expired reset code.", error_code="INVALID_OTP")

    user = db.query(User).filter(
        User.id == reset_data["user_id"], User.deleted == False  # noqa: E712
    ).first()
    if not user or not user.is_active:
        rdel(reset_key)
        raise BadRequestError("Account unavailable.", error_code="ACCOUNT_INACTIVE")

    if hasattr(user, "set_password"):
        user.set_password(data.new_password)
    else:
        user.password_hash = hash_password(data.new_password)
    db.commit()
    rdel(reset_key)

    # EDGE: a password reset should ideally invalidate any tokens issued
    # before it. Without a `user.token_version` column embedded in JWTs,
    # this can't revoke pre-reset access tokens — only future
    # blacklist-based revocations (explicit signout) are covered.
    # TODO: add token_version to User + JWT claims to close this gap.

    return api_response(
        True,
        "Password reset successfully. You can now sign in.",
        data={"email": user.email},
    )


@router.post("/forgot-password/resend", summary="Resend password reset code")
async def resend_reset_code(
    data: dict,
    background_tasks: BackgroundTasks,
):
    token = (data or {}).get("token", "")
    if not token:
        raise ValidationException("Token is required.", field_errors={"token": ["Required"]})

    throttle_key = f"{PWD_RESET_RESEND_THROTTLE_PREFIX}{token}"
    if rexists(throttle_key):
        raise RateLimitExceededError(
            "Please wait before requesting another code.",
            retry_after_seconds=OTP_RESEND_WINDOW_SECONDS,
        )
    rset(throttle_key, "1", ttl=OTP_RESEND_WINDOW_SECONDS)

    reset_key = f"{PWD_RESET_PREFIX}{token}"
    reset_data = rget(reset_key)
    if not reset_data:
        raise BadRequestError("Session expired. Please start again.", error_code="RESET_SESSION_EXPIRED")

    new_code = generate_code(6)
    reset_data["reset_code"] = new_code
    reset_data["attempts"] = 0
    rset(reset_key, reset_data, ttl=PASSWORD_RESET_TTL_SECONDS)

    background_tasks.add_task(
        send_otp,
        reset_data["email"],
        reset_data.get("name") or reset_data["email"],
        new_code,
        "reset"
    )
    return api_response(True, "New reset code sent.")


@router.post("/change-password", summary="Change password while authenticated")
async def change_password(
    data: ChangePasswordSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(data.current_password, current_user.password_hash or ""):
        raise BadRequestError("Current password is incorrect.", error_code="WRONG_PASSWORD")
    if len(data.new_password) < 8:
        raise ValidationException(
            "Password must be at least 8 characters.",
            field_errors={"new_password": ["Must be at least 8 characters"]},
        )
    if data.new_password == data.current_password:
        raise BadRequestError(
            "New password must be different from the current password.",
            error_code="PASSWORD_UNCHANGED",
        )

    current_user.password_hash = hash_password(data.new_password)
    db.commit()
    return api_response(True, "Password changed successfully.")


# ─────────────────────────────────────────────────────────────────────────
# Impersonation (admin/super_admin only — see require_admin scoping)
# ─────────────────────────────────────────────────────────────────────────

@router.post("/impersonate/{target_user_id}", summary="Admin: obtain a short-lived impersonation token")
async def impersonate(
    target_user_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Issues a short-lived token scoped to `target_user_id`. Frontend keeps
    the admin's own token cached and calls /auth/signout (with the
    impersonation token) to end the session and return to normal.

    EDGE CASES:
    - Cannot impersonate yourself.
    - Cannot impersonate a super_admin (privilege escalation guard).
    - A regular org admin cannot impersonate a user outside their org;
      only a super_admin may cross organization boundaries.
    - Target must be active and not soft-deleted.
    """
    target = db.query(User).filter(
        User.id == target_user_id, User.deleted == False  # noqa: E712
    ).first()
    if not target:
        raise NotFoundError("User", target_user_id)
    if target.id == admin.id:
        raise BadRequestError("Cannot impersonate yourself.", error_code="SELF_IMPERSONATION")
    if not target.is_active:
        raise ForbiddenError("Cannot impersonate an inactive account.", error_code="ACCOUNT_INACTIVE")
    if _is_super_admin(target):
        raise ForbiddenError("Cannot impersonate a super admin account.")

    if not _is_super_admin(admin) and target.organization_id != admin.organization_id:
        raise ForbiddenError("Cannot impersonate a user outside your organization.")

    imp_token = create_impersonation_token(
        target_user_id=str(target.id),
        impersonator_id=str(admin.id),
        impersonator_email=admin.email,
        expires_minutes=120,
    )
    logger.warning(
        "IMPERSONATION: admin_id=%s (%s) -> target_id=%s (%s)",
        admin.id, admin.email, target.id, target.email,
    )
    return api_response(
        True,
        f"Impersonation token for {target.names or target.username}",
        data={
            "access_token": imp_token,
            "token_type": "Bearer",
            "impersonated_by": {"id": admin.id, "name": admin.names, "email": admin.email},
            "user": target.get_summary(),
        },
    )

