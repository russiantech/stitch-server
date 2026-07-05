"""app/schemas/orders.py — Laundry and Fashion order schemas."""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from app.enums.stitch import (
    OrderPriority, PaymentMethodType,
    LaundryStatus, FashionStatus, FashionServiceType,
)


class GarmentItemIn(BaseModel):
    garment_type_id: Optional[str] = None
    garment_name: str              = Field(..., min_length=1)
    category: Optional[str]        = None
    quantity: int                  = Field(..., gt=0)
    unit_price: Decimal            = Field(..., ge=0)
    service_multiplier: Decimal    = Field(default=1.0, ge=0)


class GarmentItemOut(BaseModel):
    id: UUID
    garment_type_id: Optional[UUID]
    garment_name: str
    category: Optional[str]
    quantity: int
    unit_price: Decimal
    service_multiplier: Decimal
    line_total: Decimal

    model_config = {"from_attributes": True}


class StatusHistoryOut(BaseModel):
    id: UUID
    from_status: Optional[str]
    to_status: str
    notes: Optional[str]
    is_reversal: bool
    created_at: datetime
    changed_by_name: Optional[str] = None

    model_config = {"from_attributes": True}


class SubAllocationItem(BaseModel):
    subscription_id: str
    units: int = Field(..., gt=0)


# ── Laundry Order ─────────────────────────────────────────────────────────────

class LaundryServiceIn(BaseModel):
    id: str
    name: str
    price_multiplier: float


class LaundryOrderCreate(BaseModel):
    # Services
    services: List[LaundryServiceIn] = Field(..., min_length=1)

    # Garments
    garments: List[GarmentItemIn]    = Field(..., min_length=1)

    # Schedule
    pickup_date: date
    pickup_time: Optional[str]       = None
    delivery_area_id: Optional[str]  = None
    delivery_address: Optional[str]  = None

    # Priority & notes
    priority: OrderPriority          = OrderPriority.NORMAL
    special_instructions: Optional[str] = None

    # Payment
    payment_method: PaymentMethodType   = PaymentMethodType.DIRECT
    subscription_id: Optional[str]      = None
    sub_allocations: Optional[List[SubAllocationItem]] = None
    payment_reference: Optional[str]    = None

    # Amounts (computed client-side, verified server-side)
    garment_subtotal: Decimal           = Field(default=0, ge=0)
    priority_surcharge: Decimal         = Field(default=0, ge=0)
    delivery_fee: Decimal               = Field(default=0, ge=0)
    total_amount: Decimal               = Field(default=0, ge=0)

    # On-behalf (admin only)
    behalf_user_id: Optional[str]       = None


class LaundryOrderUpdate(BaseModel):
    pickup_date: Optional[date]             = None
    pickup_time: Optional[str]              = None
    delivery_area_id: Optional[str]         = None
    delivery_address: Optional[str]         = None
    special_instructions: Optional[str]     = None
    internal_notes: Optional[str]           = None
    assigned_driver_id: Optional[str]       = None
    assigned_staff_id: Optional[str]        = None


class OrderStatusUpdate(BaseModel):
    status: str            = Field(..., min_length=1)
    notes: Optional[str]   = None
    is_reversal: bool      = False


class LaundryOrderOut(BaseModel):
    id: UUID
    reference: str
    customer_id: UUID
    customer_name: Optional[str]    = None
    customer_phone: Optional[str]   = None

    status: str
    laundry_status: Optional[LaundryStatus] = None
    priority: OrderPriority
    payment_method: PaymentMethodType
    payment_status: str

    pickup_date: Optional[date]
    pickup_time: Optional[str]
    delivery_area: Optional[str]    = None
    delivery_address: Optional[str]

    garment_subtotal: Decimal
    priority_surcharge: Decimal
    delivery_fee: Decimal
    total_amount: Decimal

    garment_count: Optional[int]    = None
    garment_items: List[GarmentItemOut] = []
    status_history: List[StatusHistoryOut] = []
    services_json: Optional[Any]    = None
    special_instructions: Optional[str]

    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ── Fashion Order ─────────────────────────────────────────────────────────────

class MeasurementsIn(BaseModel):
    chest: Optional[float]    = None
    waist: Optional[float]    = None
    hips: Optional[float]     = None
    shoulder: Optional[float] = None
    length: Optional[float]   = None
    sleeve: Optional[float]   = None
    inseam: Optional[float]   = None


class FashionOrderCreate(BaseModel):
    service_type: FashionServiceType
    item_name: str                      = Field(..., min_length=1, max_length=255)
    fabric_source: str                  = Field(default="customer")
    measurements: Optional[MeasurementsIn] = None
    design_notes: Optional[str]         = None
    reference_images: Optional[List[str]] = None

    preferred_delivery_date: Optional[date] = None
    consultation_date: Optional[date]   = None
    delivery_address: Optional[str]     = None

    priority: OrderPriority             = OrderPriority.NORMAL
    payment_method: PaymentMethodType   = PaymentMethodType.DIRECT
    subscription_id: Optional[str]      = None
    total_amount: Decimal               = Field(default=0, ge=0)
    behalf_user_id: Optional[str]       = None


class FashionOrderUpdate(BaseModel):
    item_name: Optional[str]            = None
    fabric_source: Optional[str]        = None
    measurements: Optional[MeasurementsIn] = None
    design_notes: Optional[str]         = None
    consultation_date: Optional[date]   = None
    fitting_date: Optional[date]        = None
    preferred_delivery_date: Optional[date] = None
    delivery_address: Optional[str]     = None
    internal_notes: Optional[str]       = None
    assigned_staff_id: Optional[str]    = None


class FashionOrderOut(BaseModel):
    id: UUID
    reference: str
    customer_id: UUID
    customer_name: Optional[str]    = None
    customer_phone: Optional[str]   = None

    status: str
    fashion_status: Optional[FashionStatus] = None
    service_type: Optional[FashionServiceType] = None
    item_name: Optional[str]
    fabric_source: Optional[str]
    measurements: Optional[Dict[str, Any]]
    design_notes: Optional[str]
    reference_images: Optional[List[str]]

    priority: OrderPriority
    payment_method: PaymentMethodType
    payment_status: str
    total_amount: Decimal

    consultation_date: Optional[date]
    fitting_date: Optional[date]
    delivery_address: Optional[str]

    status_history: List[StatusHistoryOut] = []
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}
