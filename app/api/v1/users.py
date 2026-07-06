
# v2
"""
app/api/v1/users.py — User profile, addresses, and admin user management.

Tenancy & visibility rules
---------------------------
- super_admin: sees and manages users across every organization.
- org admin / manager (any role in require_roles("admin", "super_admin")
  on a list/get/update/delete route): scoped to their own organization
  only — enforced centrally by `_scoped_user_query`, never re-derived
  per-route, so a forgotten filter can't leak cross-tenant data.
- Activation of an *org-admin* account (i.e. approving a brand-new
  organization's first signup) is super_admin only. A regular org admin
  may freely activate/deactivate their own staff.
- Only a super_admin may grant or revoke the super_admin role, and only
  a super_admin may reset another org-admin's password or delete an
  org-admin account.

Addresses are user-owned, not org-scoped, and never exposed via the
admin endpoints below — a user's own address book is only visible to
that user via /users/me/addresses.
"""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from app.enums.stitch import UserStatus
from sqlalchemy import or_, desc
from sqlalchemy.orm import Session, joinedload

from app.api.deps.users import _get_org_id, get_db, get_current_user
from app.api.deps.rbac import require_roles
from app.core.exceptions.custom_exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    OrganizationLimitError,
    ValidationException,
)
from app.models.users import User, Address
from app.models.organization import Organization
from app.models.rbac import Role
from app.schemas.users import (
    UserUpdate, UserAdminUpdate,
    AddressCreate, AddressUpdate, AddressOut, InviteUserRequest,
)
from app.core.security.auth import hash_password
from app.utils.responses import api_response

logger = logging.getLogger(__name__)
router = APIRouter(tags=["users"])

DEFAULT_FREE_TIER_MAX_USERS = 5


# ─────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────

def _is_super_admin(user: User) -> bool:
    return any(getattr(r, "name", None) == "super_admin" for r in (user.roles or []))


def _is_org_admin_account(user: User) -> bool:
    return bool(getattr(user, "is_org_admin", False)) or _is_super_admin(user)


def _scoped_user_query(db: Session, current_user: User):
    """Super admins see every user across every organization.
    Everyone else is confined to their own organization."""
    q = db.query(User).filter(User.deleted == False)  # noqa: E712
    if not _is_super_admin(current_user):
        q = q.filter(User.organization_id == _get_org_id(current_user))
    return q


def _get_scoped_user_or_404(db: Session, current_user: User, user_id: str) -> User:
    user = _scoped_user_query(db, current_user).filter(User.id == user_id).first()
    if not user:
        raise NotFoundError("User", user_id)
    return user


def _assert_can_modify_privileged_account(current_user: User, target: User) -> None:
    if not _is_super_admin(current_user) and _is_org_admin_account(target):
        raise ForbiddenError("Not permitted to modify this account.")


# ─────────────────────────────────────────────────────────────────────────
# Current user — profile
# ─────────────────────────────────────────────────────────────────────────

@router.get("/me", summary="Get own profile")
async def get_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db_user = (
        db.query(User)
        .options(joinedload(User.addresses))
        .filter(User.id == current_user.id)
        .first()
    )
    if not db_user:
        raise NotFoundError("User", current_user.id)

    org_summary = None
    if db_user.organization_id and db_user.organization:
        org_summary = db_user.organization.get_summary()

    return api_response(True, "Profile fetched.", data={**db_user.get_summary(), "organization": org_summary})


@router.put("/me", summary="Update own profile")
async def update_profile(
    data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload = data.model_dump(exclude_unset=True)

    # Strip privileged fields — users must not self-escalate.
    # for forbidden_field in ("is_org_admin", "is_active", "organization_id", "roles"):
    #     payload.pop(forbidden_field, None)
    
    for forbidden_field in ("is_org_admin", "status", "is_active", "organization_id", "roles"):
        payload.pop(forbidden_field, None)

    if "username" in payload and payload["username"] != current_user.username:
        new_username = payload["username"].lower().strip()
        if db.query(User).filter(
            User.username == new_username, User.id != current_user.id, User.deleted == False  # noqa: E712
        ).first():
            raise ConflictError("Username is already taken.", field="username")
        payload["username"] = new_username

    if "email" in payload and payload["email"] != current_user.email:
        new_email = payload["email"].lower().strip()
        if db.query(User).filter(
            User.email == new_email, User.id != current_user.id, User.deleted == False  # noqa: E712
        ).first():
            raise ConflictError("An account with this email already exists.", field="email")
        payload["email"] = new_email
        # EDGE: email change requires re-verification.
        # TODO: wire to the Redis-staged OTP flow once /users/me/email-change exists.
        payload["email_verified"] = False

    for field, value in payload.items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return api_response(True, "Profile updated.", data=current_user.get_summary())


# ─────────────────────────────────────────────────────────────────────────
# Current user — addresses
# ─────────────────────────────────────────────────────────────────────────

@router.get("/me/addresses", summary="List own addresses")
async def list_addresses(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    addrs = (
        db.query(Address)
        .filter(Address.user_id == current_user.id)
        .order_by(Address.is_default.desc(), Address.created_at)
        .all()
    )
    return api_response(True, "Addresses fetched.", data=[AddressOut.model_validate(a) for a in addrs])


@router.post("/me/addresses", status_code=201, summary="Add an address")
async def create_address(
    payload: AddressCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.is_default:
        db.query(Address).filter(Address.user_id == current_user.id).update({"is_default": False})

    addr = Address(user_id=current_user.id, **payload.model_dump())
    if not db.query(Address).filter(Address.user_id == current_user.id).count():
        addr.is_default = True  # EDGE: first address is always default.

    db.add(addr)
    db.commit()
    db.refresh(addr)
    return api_response(True, "Address saved.", data=AddressOut.model_validate(addr), status_code=201)


@router.put("/me/addresses/{address_id}", summary="Update an address")
async def update_address(
    address_id: str,
    payload: AddressUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    addr = db.query(Address).filter(Address.id == address_id, Address.user_id == current_user.id).first()
    if not addr:
        raise NotFoundError("Address", address_id)

    if payload.is_default:
        db.query(Address).filter(Address.user_id == current_user.id).update({"is_default": False})

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(addr, field, value)
    db.commit()
    db.refresh(addr)
    return api_response(True, "Address updated.", data=AddressOut.model_validate(addr))


@router.delete("/me/addresses/{address_id}", summary="Delete an address")
async def delete_address(
    address_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    addr = db.query(Address).filter(Address.id == address_id, Address.user_id == current_user.id).first()
    if not addr:
        raise NotFoundError("Address", address_id)

    was_default = addr.is_default
    db.delete(addr)
    db.flush()

    if was_default:
        # EDGE: promote next-oldest address to default.
        next_addr = (
            db.query(Address)
            .filter(Address.user_id == current_user.id)
            .order_by(Address.created_at)
            .first()
        )
        if next_addr:
            next_addr.is_default = True

    db.commit()
    return api_response(True, "Address removed.")


@router.put("/me/addresses/{address_id}/default", summary="Set default address")
async def set_default_address(
    address_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    addr = db.query(Address).filter(Address.id == address_id, Address.user_id == current_user.id).first()
    if not addr:
        raise NotFoundError("Address", address_id)
    db.query(Address).filter(Address.user_id == current_user.id).update({"is_default": False})
    addr.is_default = True
    db.commit()
    db.refresh(addr)
    return api_response(True, "Default address updated.", data=AddressOut.model_validate(addr))


# ─────────────────────────────────────────────────────────────────────────
# Admin: list / get / update / delete users
# ─────────────────────────────────────────────────────────────────────────

@router.get(
    "/",
    summary="List users — super_admin sees all organizations, admin sees own org",
    dependencies=[Depends(require_roles("admin", "super_admin"))],
)
async def list_users(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    # is_active: Optional[bool] = None,
    status: Optional[UserStatus] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = _scoped_user_query(db, current_user)

    if search:
        term = f"%{search.strip()}%"
        q = q.filter(or_(User.names.ilike(term), User.email.ilike(term), User.username.ilike(term)))
    # if is_active is not None:
    #     q = q.filter(User.status == UserStatus.ACTIVE if is_active else UserStatus.INACTIVE)
    if status is not None:
        q = q.filter(User.status == status)
        
    total = q.count()
    users = q.order_by(desc(User.created_at)).offset((page - 1) * page_size).limit(page_size).all()
    items = [u.get_summary() for u in users]
    total_pages = (total + page_size - 1) // page_size if page_size else 0

    return api_response(True, "Users fetched.", data={
        "items": items,
        "pagination": {
            "page": page, "page_size": page_size, "total": total,
            "total_pages": total_pages, "has_next": page < total_pages, "has_prev": page > 1,
        },
    })


@router.get(
    "/{user_id}",
    summary="Get a specific user — super_admin: any org, admin: own org only",
    dependencies=[Depends(require_roles("admin", "super_admin"))],
)
async def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = _get_scoped_user_or_404(db, current_user, user_id)
    return api_response(True, "User fetched.", data=user.get_summary())


@router.put(
    "/{user_id}",
    summary="Update user — activation of org-admin accounts is super_admin only",
    dependencies=[Depends(require_roles("admin", "super_admin"))],
)
async def admin_update_user(
    user_id: str,
    data: UserAdminUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = _get_scoped_user_or_404(db, current_user, user_id)
    payload = data.model_dump(exclude_unset=True)
    is_super = _is_super_admin(current_user)

    if any(field in payload for field in ("is_active", "status")) and not is_super and _is_org_admin_account(user):
        raise ForbiddenError("Only a super admin can activate or suspend an organization's admin account.")

    if not is_super:
        for restricted_field in ("is_org_admin", "organization_id"):
            payload.pop(restricted_field, None)

    # if payload.get("is_active") is False or payload.get("status") == UserStatus.INACTIVE and _is_org_admin_account(user) and user.organization_id:
    #     other_active_admins = (
    #         db.query(User)
    #         .filter(
    #             User.organization_id == user.organization_id,
    #             User.is_org_admin == True,  # noqa: E712
    #             User.status == UserStatus.ACTIVE,  # noqa: E712
    #             User.deleted == False,  # noqa: E712
    #             User.id != user.id,
    #         )
    #         .count()
    #     )
    if payload.get("status") in (UserStatus.INACTIVE, UserStatus.SUSPENDED) and _is_org_admin_account(user) and user.organization_id:
        other_active_admins = (
            db.query(User)
            .filter(
                User.organization_id == user.organization_id,
                User.is_org_admin == True,  # noqa: E712
                User.status == UserStatus.ACTIVE,
                User.deleted == False,  # noqa: E712
                User.id != user.id,
            )
            .count()
        )
        if other_active_admins == 0:
            raise BadRequestError(
                "Cannot deactivate the last active admin of an organization.",
                error_code="LAST_ADMIN_PROTECTED",
            )

    if "username" in payload and payload["username"] != user.username:
        new_username = payload["username"].lower().strip()
        if _scoped_user_query(db, current_user).filter(
            User.username == new_username, User.id != user.id
        ).first():
            raise ConflictError("Username is already taken.", field="username")
        payload["username"] = new_username

    for field, value in payload.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)

    # action_logged = (
    #     "activated" if payload.get("is_active") is True
    #     else "deactivated" if payload.get("is_active") is False
    #     else "updated"
    # )
    new_status = payload.get("status")
    action_logged = (
        "activated" if new_status == UserStatus.ACTIVE
        else "deactivated" if new_status in (UserStatus.INACTIVE, UserStatus.SUSPENDED)
        else "updated"
    )
    
    logger.info("%s %s user %s (org=%s)", current_user.username, action_logged, user.username, user.organization_id)
    return api_response(True, "User updated.", data=user.get_summary())


@router.post(
    "/{user_id}/reset-password",
    summary="Admin reset user password — super_admin: any org, admin: own org only",
    dependencies=[Depends(require_roles("admin", "super_admin"))],
)
async def admin_reset_password(
    user_id: str,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = _get_scoped_user_or_404(db, current_user, user_id)
    _assert_can_modify_privileged_account(current_user, user)

    new_password = (data or {}).get("new_password")
    if not new_password or len(new_password) < 8:
        raise ValidationException(
            "Password must be at least 8 characters.",
            field_errors={"new_password": ["Must be at least 8 characters"]},
        )

    user.password_hash = hash_password(new_password)
    db.commit()

    logger.info("%s reset password for user %s", current_user.username, user.username)
    return api_response(True, f"Password reset for {user.username}.", data={"email": user.email})


@router.delete(
    "/{user_id}",
    summary="Soft-delete a user — super_admin: any org, admin: own org only",
    dependencies=[Depends(require_roles("admin", "super_admin"))],
)
async def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = _get_scoped_user_or_404(db, current_user, user_id)

    if user.id == current_user.id:
        raise BadRequestError("Cannot delete your own account.", error_code="SELF_DELETE_FORBIDDEN")

    _assert_can_modify_privileged_account(current_user, user)

    if _is_org_admin_account(user) and user.organization_id:
        
        # other_active_admins = (
        #     db.query(User)
        #     .filter(
        #         User.organization_id == user.organization_id,
        #         User.is_org_admin == True,  # noqa: E712
        #         User.status == UserStatus.ACTIVE,  # noqa: E712
        #         User.deleted == False,  # noqa: E712
        #         User.id != user.id,
        #     )
        #     .count()
        # )
        
        other_active_admins = (
            db.query(User)
            .filter(
                User.organization_id == user.organization_id,
                User.is_org_admin == True,  # noqa: E712
                User.status == UserStatus.ACTIVE,  # noqa: E712
                User.deleted == False,  # noqa: E712
                User.id != user.id,
            )
            .count()
        )
        
        if other_active_admins == 0:
            raise BadRequestError(
                "Cannot delete the last active admin of an organization.",
                error_code="LAST_ADMIN_PROTECTED",
            )

    # user.deleted = True
    # user.is_active = False
    user.deleted = True
    user.status = UserStatus.INACTIVE
    
    db.commit()
    logger.info("%s deleted user %s (org=%s)", current_user.username, user.username, user.organization_id)
    return api_response(True, "User removed.")


@router.post(
    "/invite",
    status_code=201,
    summary="Invite a new staff member to your organization (admin/manager)",
    dependencies=[Depends(require_roles("admin", "manager", "super_admin"))],
)
async def invite_user(
    payload: InviteUserRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _get_org_id(current_user)
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise NotFoundError("Organization", org_id)

    current_user_count = db.query(User).filter(
        User.organization_id == org.id, User.deleted == False  # noqa: E712
    ).count()
    max_users = org.max_users if org.max_users is not None else DEFAULT_FREE_TIER_MAX_USERS
    if current_user_count >= max_users:
        raise OrganizationLimitError(
            f"User limit reached ({max_users}). Upgrade your plan to add more users.",
            limit_type="max_users",
        )

    email = payload.email.lower().strip()
    username = (getattr(payload, "username", None) or email.split("@")[0]).lower().strip()

    existing = db.query(User).filter(
        or_(User.email == email, User.username == username), User.deleted == False  # noqa: E712
    ).first()
    if existing:
        field = "email" if existing.email == email else "username"
        raise ConflictError(f"A user with this {field} already exists.", field=field)

    import secrets as _secrets
    from datetime import datetime, timezone as _tz
    temp_password = _secrets.token_urlsafe(12)

    invited = User(
        names=payload.names,
        username=username,
        email=email,
        phone=getattr(payload, "phone", None),
        password_hash=hash_password(temp_password),
        organization_id=org.id,
        
        # is_org_admin=False,
        # is_active=False,
        # email_verified=True,
        
        is_org_admin=False,
        status=UserStatus.PENDING,
        email_verified=True,
            
        created_at=datetime.now(_tz.utc),
    )
    db.add(invited)
    db.flush()

    role_name = getattr(payload, "role", None) or "staff"
    role = db.query(Role).filter(Role.name == role_name).first()
    if role:
        invited.roles.append(role)

    db.commit()
    db.refresh(invited)

    from app.core.config import get_app_config
    frontend_url = get_app_config().hosting_config.frontend_url
    invite_url = f"{frontend_url}/accept-invite?email={invited.email}"

    from app.services.email_service import send_invite
    background.add_task(send_invite, invited.email, current_user.names, role_name, invite_url)

    logger.info("%s invited %s (%s) to org %s", current_user.username, invited.username, role_name, org.name)
    return api_response(True, "Invitation sent.", data=invited.get_summary(), status_code=201)


# ─────────────────────────────────────────────────────────────────────────
# Admin: role assignment
# ─────────────────────────────────────────────────────────────────────────

@router.post(
    "/{user_id}/roles/{role_name}",
    summary="Assign role to user — super_admin role assignable by super_admin only",
    dependencies=[Depends(require_roles("admin", "super_admin"))],
)
async def assign_role(
    user_id: str,
    role_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if role_name == "super_admin" and not _is_super_admin(current_user):
        raise ForbiddenError("Only a super admin can grant the super_admin role.")

    user = _get_scoped_user_or_404(db, current_user, user_id)
    role = db.query(Role).filter(Role.name == role_name).first()
    if not role:
        raise NotFoundError("Role", role_name)

    if role not in user.roles:
        user.roles.append(role)
        db.commit()
        db.refresh(user)
        logger.info("%s assigned role '%s' to %s", current_user.username, role_name, user.username)

    return api_response(True, f"Role '{role_name}' assigned to {user.username}.", data=user.get_summary())


@router.delete(
    "/{user_id}/roles/{role_name}",
    summary="Remove role from user",
    dependencies=[Depends(require_roles("admin", "super_admin"))],
)
async def remove_role(
    user_id: str,
    role_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if role_name == "super_admin" and not _is_super_admin(current_user):
        raise ForbiddenError("Only a super admin can revoke the super_admin role.")

    user = _get_scoped_user_or_404(db, current_user, user_id)
    role = db.query(Role).filter(Role.name == role_name).first()
    if role and role in user.roles:
        user.roles.remove(role)
        db.commit()
        db.refresh(user)
        logger.info("%s removed role '%s' from %s", current_user.username, role_name, user.username)

    return api_response(True, f"Role '{role_name}' removed from {user.username}.", data=user.get_summary())

