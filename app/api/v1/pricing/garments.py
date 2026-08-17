# v3 — is_global now stamped once, inside the effective-items helper
"""app/api/v1/pricing/garments.py — Garment types."""

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user, require_admin
from app.core.exceptions.custom_exceptions import ConflictError, NotFoundError
from app.db.database import get_db
from app.models.pricing import GarmentType, GarmentTypeOverride
from app.models.users import User
from app.schemas.pricing import GarmentTypeCreate, GarmentTypeOut, GarmentTypeUpdate
from app.utils.responses import api_response

router = APIRouter(tags=["Pricing"])


def _effective_garment_types(db: Session, organization_id: str, include_inactive: bool = False):
    """Global defaults (minus any this org has hidden) + this org's own
    garment types. Also stamps `is_global` on each returned row in the same
    pass, so every caller of this helper gets a correct value for free —
    no router needs to compute it separately."""
    hidden_ids = {
        row.garment_type_id for row in db.query(GarmentTypeOverride.garment_type_id).filter(
            GarmentTypeOverride.organization_id == organization_id
        ).all()
    }
    q = db.query(GarmentType).filter(
        or_(GarmentType.organization_id.is_(None), GarmentType.organization_id == organization_id)
    )
    if not include_inactive:
        q = q.filter(GarmentType.is_active.isnot(False))
    items = q.order_by(GarmentType.display_order, GarmentType.name).all()

    visible = []
    for item in items:
        if item.organization_id is None and item.id in hidden_ids:
            continue
        item.is_global = item.organization_id is None
        visible.append(item)
    return visible


@router.get("/garments")
def list_garments(include_inactive: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = _effective_garment_types(db, user.organization_id, include_inactive)
    return api_response(True, "Garment types fetched.", data=[GarmentTypeOut.model_validate(i) for i in items])


@router.post("/garments", status_code=201)
def create_garment(p: GarmentTypeCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    # Created scoped to the admin's own org — never global. Global defaults
    # are only ever seeded via the one-off script, same convention as
    # fashion and laundry services.
    existing = {
        (g.name, g.category) for g in _effective_garment_types(db, admin.organization_id, include_inactive=True)
    }
    if (p.name, p.category) in existing:
        raise ConflictError(f"Garment type '{p.name}' in category '{p.category}' already exists.")
    item = GarmentType(organization_id=admin.organization_id, **p.model_dump())
    db.add(item); db.flush()
    return api_response(
        success=True, message="Garment type created.",
        data=GarmentTypeOut.model_validate(item), status_code=201,
    )


@router.put("/garments/{item_id}")
def update_garment(item_id: str, p: GarmentTypeUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    # Deliberately scoped to organization_id == admin's own org — an admin
    # can never edit another org's garment type, and can never edit a
    # global default through this endpoint (use hide/unhide instead).
    item = db.query(GarmentType).filter(
        GarmentType.id == item_id, GarmentType.organization_id == admin.organization_id
    ).first()
    if not item:
        raise NotFoundError("Garment type", item_id)
    for k, v in p.model_dump(exclude_none=True).items():
        setattr(item, k, v)
    return api_response(success=True, message="Updated.", data=GarmentTypeOut.model_validate(item))


@router.delete("/garments/{item_id}")
def delete_garment(item_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.query(GarmentType).filter(
        GarmentType.id == item_id, GarmentType.organization_id == admin.organization_id
    ).first()
    if not item:
        raise NotFoundError("Garment type", item_id)
    item.is_active = False
    return api_response(success=True, message="Garment type deactivated.", data=None)


@router.post("/garments/{item_id}/hide")
def hide_default_garment(item_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    g = db.query(GarmentType).filter(GarmentType.id == item_id, GarmentType.organization_id.is_(None)).first()
    if not g:
        raise NotFoundError("Global garment type", item_id)
    exists = db.query(GarmentTypeOverride).filter(
        GarmentTypeOverride.organization_id == admin.organization_id,
        GarmentTypeOverride.garment_type_id == item_id,
    ).first()
    if not exists:
        db.add(GarmentTypeOverride(organization_id=admin.organization_id, garment_type_id=item_id))
        db.commit()
    return api_response(success=True, message="Default garment type hidden for your organization.")


@router.post("/garments/{item_id}/unhide")
def unhide_default_garment(item_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    db.query(GarmentTypeOverride).filter(
        GarmentTypeOverride.organization_id == admin.organization_id,
        GarmentTypeOverride.garment_type_id == item_id,
    ).delete()
    db.commit()
    return api_response(success=True, message="Default garment type restored.")

