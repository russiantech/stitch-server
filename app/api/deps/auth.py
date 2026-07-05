"""
app/api/deps/auth.py — FastAPI auth dependencies for Stitch.
Follows the same pattern as the Intellect reference implementation.
"""
import logging
from typing import Optional
import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions.custom_exceptions import CustomAPIException, AuthorizationException as ForbiddenError
from app.core.security.auth import decode_token
from app.db.database import get_db
from app.enums.stitch import UserStatus
from app.models.users import User
from app.services.redis_service import is_token_blacklisted

logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)


def _get_user_from_token(token: str, db: Session) -> Optional[User]:
    if is_token_blacklisted(token):
        return None
    payload = decode_token(token)
    if not payload:
        return None
    token_type = payload.get("type")
    if token_type not in ("access", "impersonation"):
        return None
    
    # user_id = payload.get("sub")
    # if not user_id:
    #     return None
    # user = db.get(User, uuid.UUID(user_id))
    
    user_id = payload.get("sub")
    if not user_id:
        return None
    try:
        user = db.get(User, uuid.UUID(user_id))
    except (ValueError, TypeError):
        return None
    
    if not user or user.deleted:
        return None
    if user.status in (UserStatus.SUSPENDED, UserStatus.INACTIVE):
        raise CustomAPIException("Account is suspended or inactive.", 403, "ACCOUNT_INACTIVE")
    return user


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise CustomAPIException("Authentication required.", 401, "MISSING_TOKEN")
    user = _get_user_from_token(credentials.credentials, db)
    if not user:
        raise CustomAPIException("Invalid or expired token.", 401, "INVALID_TOKEN")
    return user


def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Optional[User]:
    if not credentials:
        return None
    try:
        return _get_user_from_token(credentials.credentials, db)
    except Exception:
        logger.exception("Error occurred while fetching user from token.")
        return None


# def require_admin(user: User = Depends(get_current_user)) -> User:
#     if user.role != UserRole.ADMIN:
#         raise ForbiddenError("Admin access required.")
#     return user


# def require_staff_or_admin(user: User = Depends(get_current_user)) -> User:
#     if user.role not in (UserRole.ADMIN, UserRole.STAFF):
#         raise ForbiddenError("Staff or admin access required.")
#     return user

def require_admin(user: User = Depends(get_current_user)) -> User:
       if not user.has_role("admin", "super_admin"):
           raise ForbiddenError("Admin access required.")
       return user

def require_staff_or_admin(user: User = Depends(get_current_user)) -> User:
    if not user.has_role("admin", "staff", "super_admin"):
        raise ForbiddenError("Staff or admin access required.")
    return user

def require_driver(user: User = Depends(get_current_user)) -> User:
    if not user.has_role("admin", "driver", "super_admin"):
        raise ForbiddenError("Driver access required.")
    return user


def require_verified(user: User = Depends(get_current_user)) -> User:
    if not user.is_verified:
        raise CustomAPIException("Email verification required.", 403, "UNVERIFIED_EMAIL")
    return user

