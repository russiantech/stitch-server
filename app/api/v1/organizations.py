
"""app/api/v1/organizations.py — Organization self-management for admins."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps.users import get_db, get_current_user
from app.api.deps.rbac import require_roles
from app.core.exceptions.custom_exceptions import ForbiddenError, NotFoundError
from app.models.organization import Organization
from app.models.users import User
from app.utils.responses import api_response

router = APIRouter(tags=["Organizations"])


@router.get("/me", summary="Get own organization details")
async def get_my_org(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.organization_id:
        raise NotFoundError("Organization", "none")
    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    if not org:
        raise NotFoundError("Organization", current_user.organization_id)
    return api_response(True, "Organization fetched.", data=org.get_summary())


@router.post(
    "/me/invite-code/reset",
    summary="Generate a new invite code for your organization",
    dependencies=[Depends(require_roles("admin", "super_admin"))],
)
async def reset_invite_code(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Regenerates the org's invite code. The old code immediately stops working.
    Share the new code (or the link below) with members you want to invite."""
    if not current_user.organization_id:
        raise NotFoundError("Organization", "none")
    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    if not org:
        raise NotFoundError("Organization", current_user.organization_id)
    if not current_user.is_org_admin and not current_user.has_role("super_admin"):
        raise ForbiddenError("Only organization admins can reset the invite code.")

    org.invite_code = Organization.generate_invite_code()
    db.commit()

    from app.core.config import get_app_config
    frontend_url = get_app_config().hosting_config.frontend_url
    invite_link = f"{frontend_url}/signup?org={org.invite_code}"

    return api_response(
        True,
        "Invite code reset successfully.",
        data={
            "invite_code": org.invite_code,
            "invite_link": invite_link,
        },
    )


@router.get(
    "/me/invite-link",
    summary="Get the current invite link for your organization",
    dependencies=[Depends(require_roles("admin", "super_admin", "manager"))],
)
async def get_invite_link(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.organization_id:
        raise NotFoundError("Organization", "none")
    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    if not org:
        raise NotFoundError("Organization", current_user.organization_id)

    if not org.invite_code:
        org.invite_code = Organization.generate_invite_code()
        db.commit()

    from app.core.config import get_app_config
    frontend_url = get_app_config().hosting_config.frontend_url
    invite_link = f"{frontend_url}/signup?org={org.invite_code}"

    return api_response(
        True,
        "Invite link fetched.",
        data={
            "invite_code": org.invite_code,
            "invite_link": invite_link,
            "allow_public_signup": org.allow_public_signup,
        },
    )


@router.patch(
    "/me/public-signup",
    summary="Toggle whether the invite link allows self-signup",
    dependencies=[Depends(require_roles("admin", "super_admin"))],
)
async def toggle_public_signup(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.organization_id:
        raise NotFoundError("Organization", "none")
    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    if not org:
        raise NotFoundError("Organization", current_user.organization_id)

    allow = bool((data or {}).get("allow_public_signup", False))
    org.allow_public_signup = allow
    db.commit()

    return api_response(
        True,
        f"Public signup {'enabled' if allow else 'disabled'}.",
        data={"allow_public_signup": org.allow_public_signup},
    )

@router.get("/lookup/{invite_code}", summary="Public: resolve an invite code to basic org info (pre-signup)")
def lookup_org_by_code(invite_code: str, db: Session = Depends(get_db)):
    org = db.query(Organization).filter(
        Organization.invite_code == invite_code.upper().strip(),
        Organization.deleted == False,
    ).first()
    if not org:
        raise NotFoundError("Organization", invite_code)
    if not org.is_active or org.is_paused:
        raise ForbiddenError("This organization is not currently accepting new members.")
    if not org.allow_public_signup:
        raise ForbiddenError("This organization requires an admin invitation to join.")
    return api_response(True, "Organization found.", data={"name": org.name, "invite_code": org.invite_code})