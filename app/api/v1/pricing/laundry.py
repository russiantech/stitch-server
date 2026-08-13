"""app/api/v1/pricing.py — Garment types, laundry services, delivery areas."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user, require_admin
from app.core.exceptions.custom_exceptions import ConflictError, NotFoundError
from app.db.database import get_db
from app.models.pricing import LaundryService
from app.models.users import User
from app.schemas.pricing import (
    LaundryServiceCreate, LaundryServiceOut, LaundryServiceUpdate,
)
from app.utils.responses import api_response

router = APIRouter(tags=["Pricing"])

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

