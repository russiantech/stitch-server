"""app/schemas/inventory.py — Inventory schemas."""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field
from app.enums.stitch import InventoryCategory, InventoryLogAction


class InventoryItemCreate(BaseModel):
    name: str              = Field(..., min_length=2, max_length=200)
    category: InventoryCategory
    quantity: int          = Field(default=0, ge=0)
    unit: str              = Field(..., min_length=1, max_length=30)
    reorder_level: int     = Field(default=0, ge=0)
    unit_cost: Optional[Decimal] = None
    supplier: Optional[str]      = None
    notes: Optional[str]         = None


class InventoryItemUpdate(BaseModel):
    name: Optional[str]    = None
    category: Optional[InventoryCategory] = None
    quantity: Optional[int] = Field(None, ge=0)
    unit: Optional[str]     = None
    reorder_level: Optional[int] = None
    unit_cost: Optional[Decimal] = None
    supplier: Optional[str]      = None
    notes: Optional[str]         = None


class InventoryAdjustRequest(BaseModel):
    action: InventoryLogAction
    quantity_change: int   = Field(..., ne=0)
    reason: Optional[str]  = None


class InventoryItemOut(BaseModel):
    id: UUID
    name: str
    category: InventoryCategory
    quantity: int
    unit: str
    reorder_level: int
    unit_cost: Optional[Decimal]
    supplier: Optional[str]
    notes: Optional[str]
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}

