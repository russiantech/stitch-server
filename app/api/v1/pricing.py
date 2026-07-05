"""app/api/v1/pricing.py — Garment types, laundry services, delivery areas."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user, require_admin
from app.core.exceptions.custom_exceptions import ConflictError, NotFoundError
from app.db.database import get_db
from app.models.pricing import DeliveryArea, GarmentType, LaundryService
from app.models.users import User
from app.schemas.pricing import (
    DeliveryAreaCreate, DeliveryAreaOut, DeliveryAreaUpdate,
    GarmentTypeCreate, GarmentTypeOut, GarmentTypeUpdate,
    LaundryServiceCreate, LaundryServiceOut, LaundryServiceUpdate,
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


# ─── Laundry Services ─────────────────────────────────────────────────────────

@router.get("/services")
def list_services(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.query(LaundryService).filter(LaundryService.is_active == True).order_by(
        LaundryService.display_order
    ).all()
    return api_response(
        success=True,
        message="Services fetched.",
        data=[LaundryServiceOut.model_validate(i) for i in items],
    )


@router.post("/services", status_code=201)
def create_service(p: LaundryServiceCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    exists = db.query(LaundryService).filter(LaundryService.name == p.name).first()
    if exists: raise ConflictError(f"Service '{p.name}' already exists.")
    item = LaundryService(**p.model_dump()); db.add(item); db.flush()
    return api_response(
        success=True,
        message="Service created.",
        data=LaundryServiceOut.model_validate(item),
        status_code=201,
    )


@router.put("/services/{item_id}")
def update_service(item_id: str, p: LaundryServiceUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.get(LaundryService, item_id)
    if not item: raise NotFoundError("Service", item_id)
    for k, v in p.model_dump(exclude_none=True).items(): setattr(item, k, v)
    return api_response(
        success=True,
        message="Updated.",
        data=LaundryServiceOut.model_validate(item),
    )


@router.delete("/services/{item_id}")
def delete_service(item_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.get(LaundryService, item_id)
    if not item: raise NotFoundError("Service", item_id)
    item.is_active = False
    return api_response(
        success=True,
        message="Service deactivated.",
        data=None,
    )


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

