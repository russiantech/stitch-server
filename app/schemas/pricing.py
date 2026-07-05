"""app/schemas/pricing.py — GarmentType, LaundryService, DeliveryArea schemas."""
from datetime import datetime
from decimal import Decimal
from typing import Optional
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
    display_order: int
    created_at: datetime

    model_config = {"from_attributes": True}

