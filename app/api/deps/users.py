"""
app/api/deps/users.py — auth/db dependencies: current-user resolution,
session lifecycle, and simple flat role gates.

Role-gate split
----------------
This module owns dependencies that need only a *fixed* set of roles
known at definition time (admin_required, manager_required, etc.) and
the org-scoping helpers (_get_org_id, require_org_admin).

Anything that needs a *parameterized* set of roles decided per-route —
e.g. `Depends(require_roles("admin", "super_admin"))` as used throughout
users.py — is a dependency *factory*, not a dependency, and belongs in
app/api/deps/rbac.py (see that file). Mixing the two styles in one
module is what caused the prior ImportError; keeping them in separate,
clearly-named modules makes the distinction unmissable.

Privilege checks here are intentionally all routed through
`User.has_role(...)` (backed by the actual `roles` relationship) rather
than ad-hoc boolean columns like `is_superuser`, so there's exactly one
source of truth for "what can this user do" across every dependency,
route, and the exception/audit logging in auth.py and users.py.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.security.auth import decode_token
from sqlalchemy.orm import Session

from app.models.users import User

security = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# DB session
# ─────────────────────────────────────────────────────────────────────────
from app.db.database import get_db

# ─────────────────────────────────────────────────────────────────────────
# Current user resolution
# ─────────────────────────────────────────────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not credentials:
        raise credentials_exception

    payload = decode_token(credentials.credentials)
    if not payload:
        raise credentials_exception

    user_id: str = payload.get("sub")
    if not user_id:
        raise credentials_exception

    try:
        uid = UUID(user_id)
    except ValueError:
        raise credentials_exception

    user = db.query(User).filter(User.id == uid, User.deleted == False).first()  # noqa: E712
    if not user:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")

    # EDGE: an org can be paused (billing failure, admin lockout, abuse
    # response) without individually deactivating every member account.
    # A super_admin's organization_id may legitimately be None — that
    # case must not be treated as "paused" by falling through to a
    # missing-attribute default.
    if user.organization_id and user.organization:
        if getattr(user.organization, "is_paused", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization account is paused. Contact your administrator.",
            )

    return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    # EDGE: get_current_user already raises 403 on an inactive account
    # before this dependency ever runs, so this branch is unreachable in
    # practice — kept only so any route still depending on this name
    # directly (rather than through get_current_user) doesn't regress.
    # Status code aligned to 403 to match get_current_user's behavior
    # instead of the previous inconsistent 400.
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")
    return current_user


# ─────────────────────────────────────────────────────────────────────────
# Fixed-role gates
# ─────────────────────────────────────────────────────────────────────────

async def admin_required(current_user: User = Depends(get_current_user)) -> User:
    """Admin, super_admin, or manager. Note this is broader than its name
    implies — kept exactly as-is since app/api/v1/auth.py already imports
    it as `admin_required as require_admin` and several routes rely on
    manager-level access here (e.g. toggling org config). If a route
    needs admin-or-super_admin *without* manager, use require_roles from
    deps/rbac.py instead.
    """
    if not current_user.has_role("admin", "super_admin", "manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


async def manager_required(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.has_role("admin", "super_admin", "manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager or Admin privileges required",
        )
    return current_user


async def require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    """Strictly super_admin — no admin/manager fallback. Use for
    platform-level operations that must never be delegable to a regular
    org admin (e.g. cross-org actions, granting the super_admin role
    itself). See ForbiddenError checks in auth.py/users.py that
    currently re-derive this in route bodies via _is_super_admin(); this
    dependency exists so newly written routes can enforce it at the
    dependency layer instead of re-deriving it inline each time.
    """
    if not current_user.has_role("super_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin privileges required",
        )
    return current_user


async def require_org_admin(current_user: User = Depends(get_current_user)) -> User:
    """Org-admin-or-above, scoped to the user's own organization. Fixed
    to check the real `is_org_admin` boolean on User plus the actual
    `super_admin` role via has_role(), instead of the previous
    `is_superuser` attribute, which doesn't exist anywhere else in the
    codebase and so always evaluated to the default `False` — silently
    granting nothing rather than raising, the worst kind of bug because
    it never surfaces as an error, just as mysteriously-denied access.
    """
    is_org_admin = bool(getattr(current_user, "is_org_admin", False))
    is_super = current_user.has_role("super_admin")

    if not is_org_admin and not is_super:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization admin privileges required",
        )
    return current_user


# ─────────────────────────────────────────────────────────────────────────
# Org scoping helper
# ─────────────────────────────────────────────────────────────────────────

def _get_org_id(current_user: User) -> str:
    """Used by users.py's _scoped_user_query and invite_user to scope
    queries to the caller's own organization. A super_admin with no
    organization_id calling an org-scoped endpoint is itself a usage
    error in the route (super_admin should normally bypass
    _get_org_id entirely via the is_super_admin branch) — this still
    raises clearly here rather than returning None and letting a
    downstream `.filter(User.organization_id == None)` silently scope
    to "no organization" instead of failing loudly.
    """
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not associated with any organization",
        )
    return str(current_user.organization_id)

