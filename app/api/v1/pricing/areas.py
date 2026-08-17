# v3 — is_global now stamped once, inside the effective-items helper
"""app/api/v1/pricing/areas.py — Delivery areas."""

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user, require_admin
from app.core.exceptions.custom_exceptions import ConflictError, NotFoundError
from app.db.database import get_db
from app.models.pricing import DeliveryArea, DeliveryAreaOverride
from app.models.users import User
from app.schemas.pricing import DeliveryAreaCreate, DeliveryAreaOut, DeliveryAreaUpdate
from app.utils.responses import api_response

router = APIRouter(tags=["Pricing"])


def _effective_delivery_areas(db: Session, organization_id: str, include_inactive: bool = False):
    """Global defaults (minus any this org has hidden) + this org's own
    delivery areas. Also stamps `is_global` on each returned row in the
    same pass — same pattern as garments/laundry."""
    hidden_ids = {
        row.delivery_area_id for row in db.query(DeliveryAreaOverride.delivery_area_id).filter(
            DeliveryAreaOverride.organization_id == organization_id
        ).all()
    }
    q = db.query(DeliveryArea).filter(
        or_(DeliveryArea.organization_id.is_(None), DeliveryArea.organization_id == organization_id)
    )
    if not include_inactive:
        q = q.filter(DeliveryArea.is_active.isnot(False))
    items = q.order_by(DeliveryArea.display_order, DeliveryArea.name).all()

    visible = []
    for item in items:
        if item.organization_id is None and item.id in hidden_ids:
            continue
        item.is_global = item.organization_id is None
        visible.append(item)
    return visible


@router.get("/areas")
def list_areas(include_inactive: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = _effective_delivery_areas(db, user.organization_id, include_inactive)
    return api_response(True, "Delivery areas fetched.", data=[DeliveryAreaOut.model_validate(i) for i in items])


@router.post("/areas", status_code=201)
def create_area(p: DeliveryAreaCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    existing_names = {a.name for a in _effective_delivery_areas(db, admin.organization_id, include_inactive=True)}
    if p.name in existing_names:
        raise ConflictError(f"Area '{p.name}' already exists.")
    item = DeliveryArea(organization_id=admin.organization_id, **p.model_dump())
    db.add(item); db.flush()
    return api_response(
        success=True, message="Delivery area created.",
        data=DeliveryAreaOut.model_validate(item), status_code=201,
    )


@router.put("/areas/{item_id}")
def update_area(item_id: str, p: DeliveryAreaUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.query(DeliveryArea).filter(
        DeliveryArea.id == item_id, DeliveryArea.organization_id == admin.organization_id
    ).first()
    if not item:
        raise NotFoundError("Delivery area", item_id)
    for k, v in p.model_dump(exclude_none=True).items():
        setattr(item, k, v)
    return api_response(success=True, message="Updated.", data=DeliveryAreaOut.model_validate(item))


@router.delete("/areas/{item_id}")
def delete_area(item_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.query(DeliveryArea).filter(
        DeliveryArea.id == item_id, DeliveryArea.organization_id == admin.organization_id
    ).first()
    if not item:
        raise NotFoundError("Delivery area", item_id)
    item.is_active = False
    return api_response(success=True, message="Delivery area deactivated.", data=None)


@router.post("/areas/{item_id}/hide")
def hide_default_area(item_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    a = db.query(DeliveryArea).filter(DeliveryArea.id == item_id, DeliveryArea.organization_id.is_(None)).first()
    if not a:
        raise NotFoundError("Global delivery area", item_id)
    exists = db.query(DeliveryAreaOverride).filter(
        DeliveryAreaOverride.organization_id == admin.organization_id,
        DeliveryAreaOverride.delivery_area_id == item_id,
    ).first()
    if not exists:
        db.add(DeliveryAreaOverride(organization_id=admin.organization_id, delivery_area_id=item_id))
        db.commit()
    return api_response(success=True, message="Default delivery area hidden for your organization.")


@router.post("/areas/{item_id}/unhide")
def unhide_default_area(item_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    db.query(DeliveryAreaOverride).filter(
        DeliveryAreaOverride.organization_id == admin.organization_id,
        DeliveryAreaOverride.delivery_area_id == item_id,
    ).delete()
    db.commit()
    return api_response(success=True, message="Default delivery area restored.")

