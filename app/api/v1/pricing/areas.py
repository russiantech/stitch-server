"""app/api/v1/pricing.py — Garment types, laundry services, delivery areas."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user, require_admin
from app.core.exceptions.custom_exceptions import ConflictError, NotFoundError
from app.db.database import get_db
from app.models.pricing import DeliveryArea
from app.models.users import User
from app.schemas.pricing import (
    DeliveryAreaCreate, DeliveryAreaOut, DeliveryAreaUpdate,
)
from app.utils.responses import api_response

router = APIRouter(tags=["Pricing"])

# ─── Delivery Areas ───────────────────────────────────────────────────────────

@router.get("/areas")
def list_areas(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.query(DeliveryArea).filter(DeliveryArea.is_active == True).order_by(
        DeliveryArea.display_order, DeliveryArea.name
    ).all()
    return api_response(
        success=True,
        message="Delivery areas fetched.",
        data=[DeliveryAreaOut.model_validate(i) for i in items],
    )


@router.post("/areas", status_code=201)
def create_area(p: DeliveryAreaCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    exists = db.query(DeliveryArea).filter(DeliveryArea.name == p.name).first()
    if exists: raise ConflictError(f"Area '{p.name}' already exists.")
    item = DeliveryArea(**p.model_dump()); db.add(item); db.flush()
    return api_response(
        success=True,
        message="Delivery area created.",
        data=DeliveryAreaOut.model_validate(item),
        status_code=201,
    )


@router.put("/areas/{item_id}")
def update_area(item_id: str, p: DeliveryAreaUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.get(DeliveryArea, item_id)
    if not item: raise NotFoundError("Delivery area", item_id)
    for k, v in p.model_dump(exclude_none=True).items(): setattr(item, k, v)
    return api_response(
        success=True,
        message="Updated.",
        data=DeliveryAreaOut.model_validate(item),
    )


@router.delete("/areas/{item_id}")
def delete_area(item_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.get(DeliveryArea, item_id)
    if not item: raise NotFoundError("Delivery area", item_id)
    item.is_active = False
    return api_response(
        success=True,
        message="Delivery area deactivated.",
        data=None,
    )
