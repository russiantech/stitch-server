"""app/api/v1/pricing.py — Garment types, laundry services, delivery areas."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user, require_admin
from app.core.exceptions.custom_exceptions import NotFoundError
from app.db.database import get_db
from app.models.pricing import GarmentType
from app.models.users import User
from app.schemas.pricing import (
    GarmentTypeCreate, GarmentTypeOut, GarmentTypeUpdate,
)
from app.utils.responses import api_response

router = APIRouter(tags=["Pricing"])


# ─── Garment Types ────────────────────────────────────────────────────────────

@router.get("/garments")
def list_garments(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.query(GarmentType).filter(GarmentType.is_active == True).order_by(
        GarmentType.display_order, GarmentType.name
    ).all()
    return api_response(
        success=True,
        message="Garment types fetched.",
        data=[GarmentTypeOut.model_validate(i) for i in items],
    )


@router.post("/garments", status_code=201)
def create_garment(p: GarmentTypeCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = GarmentType(**p.model_dump()); db.add(item); db.flush()
    return api_response(
        success=True,
        message="Garment type created.",
        data=GarmentTypeOut.model_validate(item),
        status_code=201,
    )


@router.put("/garments/{item_id}")
def update_garment(item_id: str, p: GarmentTypeUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.get(GarmentType, item_id)
    if not item: raise NotFoundError("Garment type", item_id)
    for k, v in p.model_dump(exclude_none=True).items(): setattr(item, k, v)
    return api_response(
        success=True,
        message="Updated.",
        data=GarmentTypeOut.model_validate(item),
    )


@router.delete("/garments/{item_id}")
def delete_garment(item_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.get(GarmentType, item_id)
    if not item: raise NotFoundError("Garment type", item_id)
    item.is_active = False
    return api_response(
        success=True,
        message="Garment type deactivated.",
        data=None,
    )
