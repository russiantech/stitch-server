# v3 — is_global now stamped once, inside the effective-items helper
"""app/api/v1/pricing/laundry.py — Laundry service types."""

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user, require_admin
from app.core.exceptions.custom_exceptions import ConflictError, NotFoundError
from app.db.database import get_db
from app.models.pricing import LaundryService, LaundryServiceOverride
from app.models.users import User
from app.schemas.pricing import LaundryServiceCreate, LaundryServiceOut, LaundryServiceUpdate
from app.utils.responses import api_response

router = APIRouter(tags=["Pricing"])


def _effective_laundry_services(db: Session, organization_id: str, include_inactive: bool = False):
    """Global defaults (organization_id IS NULL) + this org's own services —
    same merge pattern as garments/areas. Also stamps `is_global` on each
    returned row in the same pass. Single source of truth for both listing
    and validating; do not reimplement this filter inline elsewhere."""
    hidden_ids = {
        row.laundry_service_id for row in db.query(LaundryServiceOverride.laundry_service_id).filter(
            LaundryServiceOverride.organization_id == organization_id
        ).all()
    }
    q = db.query(LaundryService).filter(
        or_(LaundryService.organization_id.is_(None), LaundryService.organization_id == organization_id)
    )
    if not include_inactive:
        q = q.filter(LaundryService.is_active.isnot(False))
    items = q.order_by(LaundryService.display_order, LaundryService.name).all()

    visible = []
    for item in items:
        if item.organization_id is None and item.id in hidden_ids:
            continue
        item.is_global = item.organization_id is None
        visible.append(item)
    return visible


@router.get("/services")
def list_services(include_inactive: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = _effective_laundry_services(db, user.organization_id, include_inactive)
    return api_response(True, "Services fetched.", data=[LaundryServiceOut.model_validate(i) for i in items])


@router.post("/services", status_code=201)
def create_service(p: LaundryServiceCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    # Uniqueness checked within THIS org's effective catalog (own services +
    # global defaults) — never platform-wide. Created scoped to the admin's
    # own org; never global — global defaults are only ever seeded via the
    # one-off script, same convention as fashion services.
    existing_names = {s.name for s in _effective_laundry_services(db, admin.organization_id, include_inactive=True)}
    if p.name in existing_names:
        raise ConflictError(f"Service '{p.name}' already exists.")
    item = LaundryService(organization_id=admin.organization_id, **p.model_dump())
    db.add(item); db.flush()
    return api_response(
        success=True, message="Service created.",
        data=LaundryServiceOut.model_validate(item), status_code=201,
    )


@router.put("/services/{item_id}")
def update_service(item_id: str, p: LaundryServiceUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    # Deliberately scoped to organization_id == admin's own org — an admin
    # can never edit another org's service, and can never edit a global
    # default (organization_id IS NULL) through this endpoint, since that
    # would silently change it for every tenant on the platform.
    item = db.query(LaundryService).filter(
        LaundryService.id == item_id, LaundryService.organization_id == admin.organization_id
    ).first()
    if not item:
        raise NotFoundError("Service", item_id)
    for k, v in p.model_dump(exclude_none=True).items():
        setattr(item, k, v)
    return api_response(success=True, message="Updated.", data=LaundryServiceOut.model_validate(item))


@router.delete("/services/{item_id}")
def delete_service(item_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.query(LaundryService).filter(
        LaundryService.id == item_id, LaundryService.organization_id == admin.organization_id
    ).first()
    if not item:
        raise NotFoundError("Service", item_id)
    item.is_active = False
    return api_response(success=True, message="Service deactivated.", data=None)


@router.post("/services/{item_id}/hide")
def hide_default_service(item_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.query(LaundryService).filter(LaundryService.id == item_id, LaundryService.organization_id.is_(None)).first()
    if not s:
        raise NotFoundError("Global service", item_id)
    exists = db.query(LaundryServiceOverride).filter(
        LaundryServiceOverride.organization_id == admin.organization_id,
        LaundryServiceOverride.laundry_service_id == item_id,
    ).first()
    if not exists:
        db.add(LaundryServiceOverride(organization_id=admin.organization_id, laundry_service_id=item_id))
        db.commit()
    return api_response(success=True, message="Default service hidden for your organization.")


@router.post("/services/{item_id}/unhide")
def unhide_default_service(item_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    db.query(LaundryServiceOverride).filter(
        LaundryServiceOverride.organization_id == admin.organization_id,
        LaundryServiceOverride.laundry_service_id == item_id,
    ).delete()
    db.commit()
    return api_response(success=True, message="Default service restored.")