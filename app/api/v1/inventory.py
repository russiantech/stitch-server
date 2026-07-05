"""app/api/v1/inventory.py — Inventory management."""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps.auth import  require_staff_or_admin
from app.core.exceptions.custom_exceptions import NotFoundError
from app.db.database import get_db
from app.enums.stitch import InventoryCategory
from app.models.inventory import InventoryItem, InventoryLog
from app.models.users import User
from app.schemas.inventory import (
    InventoryAdjustRequest, InventoryItemCreate, InventoryItemOut, InventoryItemUpdate,
)
from app.utils.responses import api_response

router = APIRouter(tags=["Inventory"])


@router.get("")
def list_inventory(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    category: Optional[InventoryCategory] = None,
    low_stock: bool = False,
    staff: User = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
):
    q = db.query(InventoryItem)
    if category:
        q = q.filter(InventoryItem.category == category)
    total = q.count()
    items = q.order_by(InventoryItem.category, InventoryItem.name).offset((page-1)*page_size).limit(page_size).all()
    out   = [InventoryItemOut.model_validate(i) for i in items]
    if low_stock:
        out = [o for o in out if o.status in ("Low Stock", "Out of Stock")]
    return api_response(
        success=True,
        message="Inventory fetched.",
        data={
            "items": out,
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


@router.post("", status_code=201)
def create_item(p: InventoryItemCreate, staff: User = Depends(require_staff_or_admin), db: Session = Depends(get_db)):
    item = InventoryItem(**p.model_dump()); db.add(item); db.flush()
    return api_response(
        success=True,
        message="Item added.",
        data=InventoryItemOut.model_validate(item),
        status_code=201,
    )


@router.put("/{item_id}")
def update_item(item_id: str, p: InventoryItemUpdate, staff: User = Depends(require_staff_or_admin), db: Session = Depends(get_db)):
    item = db.get(InventoryItem, item_id)
    if not item: raise NotFoundError("Inventory item", item_id)
    for k, v in p.model_dump(exclude_none=True).items(): setattr(item, k, v)
    return api_response(
        success=True,
        message="Updated.",
        data=InventoryItemOut.model_validate(item),
    )


@router.post("/{item_id}/adjust")
def adjust_stock(
    item_id: str, p: InventoryAdjustRequest,
    staff: User = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
):
    item = db.get(InventoryItem, item_id)
    if not item: raise NotFoundError("Inventory item", item_id)
    before = item.quantity
    item.quantity = max(0, item.quantity + p.quantity_change)
    db.add(InventoryLog(
        item_id=item.id, action=p.action,
        quantity_change=p.quantity_change,
        quantity_before=before, quantity_after=item.quantity,
        performed_by_id=staff.id, reason=p.reason,
    ))
    return api_response(
        success=True,
        message="Stock adjusted.",
        data=InventoryItemOut.model_validate(item),
    )


@router.delete("/{item_id}")
def delete_item(item_id: str, staff: User = Depends(require_staff_or_admin), db: Session = Depends(get_db)):
    item = db.get(InventoryItem, item_id)
    if not item: raise NotFoundError("Inventory item", item_id)
    db.delete(item)
    return api_response(
        success=True,
        message="Item removed.",
        data=None,
    )
