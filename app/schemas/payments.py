"""app/schemas/payments.py — Payment initiation, verification, output."""
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from app.enums.stitch import PaymentStatus, PaymentProvider, PaymentPurpose


class PaymentInitRequest(BaseModel):
    email: Optional[str]          = None
    amount: Decimal               = Field(..., gt=0)
    reference: Optional[str]      = None
    purpose: PaymentPurpose       = PaymentPurpose.ORDER
    order_id: Optional[str]       = None
    subscription_id: Optional[str] = None
    plan_id: Optional[str]        = None
    callback_url: Optional[str]   = None
    metadata: Optional[Dict[str, Any]] = None


class PaymentVerifyRequest(BaseModel):
    reference: str


class PaymentOut(BaseModel):
    id: UUID
    reference: str
    provider: PaymentProvider
    purpose: PaymentPurpose
    status: PaymentStatus
    currency: str
    amount: Decimal
    amount_paid: Optional[Decimal]
    channel: Optional[str]
    paid_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class InvoiceCreateRequest(BaseModel):
    customer_name: str  = Field(..., min_length=2)
    order_id: Optional[str] = None
    order_reference: Optional[str] = None
    amount: Decimal     = Field(..., gt=0)
    notes: Optional[str] = None

