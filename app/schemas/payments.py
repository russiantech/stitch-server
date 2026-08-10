"""app/schemas/payments.py — Payment initiation, verification, output."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_serializer
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
    amount_paid: Optional[Decimal] = None
    channel: Optional[str] = None
    paid_at: Optional[datetime] = None
    created_at: datetime
    # ── Added for CRM/Billing customer visibility (see item 6 below) ──
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None

    model_config = {"from_attributes": True}

    @field_serializer("amount", "amount_paid")
    def _serialize_decimal(self, v: Optional[Decimal]) -> Optional[float]:
        # Ensures the JSON wire value is a real number, not a string —
        # fixes NaN bugs anywhere the frontend sums/does math on these fields.
        return float(v) if v is not None else None


class InvoiceCreateRequest(BaseModel):
    customer_name: str  = Field(..., min_length=2)
    order_id: Optional[str] = None
    order_reference: Optional[str] = None
    amount: Decimal     = Field(..., gt=0)
    notes: Optional[str] = None

