"""app/schemas/pricing.py — GarmentType, LaundryService, DeliveryArea schemas."""
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class GarmentTypeCreate(BaseModel):
    name: str              = Field(..., min_length=2, max_length=150)
    category: str          = Field(..., min_length=2, max_length=80)
    base_price: Decimal    = Field(..., ge=0)
    unit: str              = Field(default="per piece", max_length=50)
    description: Optional[str] = None
    display_order: int     = 0


class GarmentTypeUpdate(BaseModel):
    name: Optional[str]         = None
    category: Optional[str]     = None
    base_price: Optional[Decimal] = Field(None, ge=0)
    unit: Optional[str]         = None
    description: Optional[str]  = None
    is_active: Optional[bool]   = None
    display_order: Optional[int] = None

class GarmentTypeOut(BaseModel):
    id: UUID
    name: str
    category: str
    base_price: Decimal
    unit: str
    description: Optional[str]
    is_active: bool
    is_global: bool = True   # ← add
    display_order: int
    created_at: datetime
    model_config = {"from_attributes": True}

class LaundryServiceCreate(BaseModel):
    name: str              = Field(..., min_length=2, max_length=150)
    description: Optional[str] = None
    price_multiplier: Decimal = Field(default=1.0, ge=0)
    icon: Optional[str]    = None
    display_order: int     = 0
    

class LaundryServiceUpdate(BaseModel):
    name: Optional[str]            = None
    description: Optional[str]     = None
    price_multiplier: Optional[Decimal] = Field(None, ge=0)
    icon: Optional[str]            = None
    is_active: Optional[bool]      = None
    display_order: Optional[int]   = None

class LaundryServiceOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    price_multiplier: Decimal
    icon: Optional[str]
    is_active: bool
    is_global: bool = False   # ← add
    display_order: int
    created_at: datetime
    model_config = {"from_attributes": True}


class DeliveryAreaCreate(BaseModel):
    name: str              = Field(..., min_length=2, max_length=150)
    price: Decimal         = Field(..., ge=0)
    state: str             = Field(default="Lagos", max_length=100)
    description: Optional[str] = None
    display_order: int     = 0


class DeliveryAreaUpdate(BaseModel):
    name: Optional[str]     = None
    price: Optional[Decimal] = Field(None, ge=0)
    state: Optional[str]    = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    display_order: Optional[int] = None

class DeliveryAreaOut(BaseModel):
    id: UUID
    name: str
    price: Decimal
    state: str
    description: Optional[str]
    is_active: bool
    is_global: bool = False   # ← add
    display_order: int
    created_at: datetime
    model_config = {"from_attributes": True}

# schema — confirm both fields exist here
class FashionFeeSettingsOut(BaseModel):
    consultation_fee: Decimal
    consultation_fee_enabled: bool
    consultation_applies_to: Optional[List[str]] = None
    material_pickup_fee: Decimal
    material_pickup_fee_enabled: bool
    material_pickup_applies_to: Optional[List[str]] = None
    model_config = {"from_attributes": True}

class FashionFeeSettingsUpdate(BaseModel):
    consultation_fee: Optional[Decimal] = None
    consultation_fee_enabled: Optional[bool] = None
    consultation_applies_to: Optional[List[str]] = None
    material_pickup_fee: Optional[Decimal] = None
    material_pickup_fee_enabled: Optional[bool] = None
    material_pickup_applies_to: Optional[List[str]] = None
# FashionService schemas — for admin-managed fashion service catalogue (replaces the previous hardcoded FashionServiceType enum entirely). 
# Each org can define its own set of fashion services (names, icons, ordering).

class FashionServiceOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    is_active: bool
    display_order: int
    is_global: bool = False
    model_config = {"from_attributes": True}

class FashionServiceCreate(BaseModel):
    name: str = Field(..., min_length=2)
    description: Optional[str] = None
    icon: Optional[str] = None
    display_order: int = 0

class FashionServiceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    is_active: Optional[bool] = None
    display_order: Optional[int] = None

