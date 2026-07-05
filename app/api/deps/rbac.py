
"""
app/api/deps/rbac.py — parameterized role-gate dependency factory.

app/api/v1/users.py does:

    dependencies=[Depends(require_roles("admin", "super_admin"))]

`require_roles(*names)` must therefore be a *factory* — a function that
takes role names and returns a FastAPI dependency — not a flat
dependency itself. That distinction is the reason this lives in its own
module separate from app/api/deps/users.py's fixed-role gates
(admin_required, manager_required, etc.): mixing factory and
non-factory dependencies under near-identical names in one file is
exactly what produced the original `cannot import name 'require_roles'`
failure.
"""

import logging
from typing import Callable

from fastapi import Depends, HTTPException, status

from app.api.deps.users import get_current_user
from app.models.users import User

logger = logging.getLogger(__name__)


def require_roles(*role_names: str) -> Callable:
    """Returns a dependency that requires the current user to hold at
    least one of `role_names` (checked via User.has_role(), the single
    source of truth used everywhere else in the codebase).

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_roles("admin", "super_admin"))])

    EDGE: an empty call — require_roles() with no arguments — would
    otherwise silently grant access to everyone (has_role() with no
    names to check). Guarded explicitly so a typo'd call site fails
    loudly at request time instead of quietly authorizing nobody-knows-who.
    """
    if not role_names:
        raise ValueError("require_roles() requires at least one role name.")

    async def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if not current_user.has_role(*role_names):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of the following roles: {', '.join(role_names)}",
            )
        return current_user

    return _dependency

