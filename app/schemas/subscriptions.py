"""app/schemas/subscriptions.py — Plan, Subscription, UsageLog schemas."""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from app.enums.stitch import PlanInterval, UsagePaymentSource
from app.enums.billing import SubscriptionStatus

class PlanCreate(BaseModel):
    name: str               = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None
    amount: Decimal         = Field(..., gt=0)
    units: int              = Field(..., gt=0)
    interval: PlanInterval  = PlanInterval.MONTHLY
    is_popular: bool        = False
    paystack_plan_code: Optional[str] = None
    display_order: int      = 0


class PlanUpdate(BaseModel):
    name: Optional[str]     = Field(None, min_length=2, max_length=100)
    description: Optional[str] = None
    amount: Optional[Decimal] = Field(None, gt=0)
    units: Optional[int]    = Field(None, gt=0)
    interval: Optional[PlanInterval] = None
    is_popular: Optional[bool] = None
    is_active: Optional[bool] = None
    paystack_plan_code: Optional[str] = None
    display_order: Optional[int] = None


class PlanOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    amount: Decimal
    units: int
    interval: PlanInterval
    is_popular: bool
    is_active: bool
    paystack_plan_code: Optional[str]
    display_order: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SubscriptionInitiateRequest(BaseModel):
    plan_id: UUID
    email: Optional[str] = None   # overrides authenticated user's email
    callback_url: Optional[str] = None


class SubscriptionOut(BaseModel):
    id: UUID
    plan_id: UUID
    plan_name: str
    interval: PlanInterval
    status: SubscriptionStatus
    units: int
    units_used: int
    units_remaining: int
    amount: Optional[Decimal]
    subscribed_at: date
    renews_at: Optional[date]
    payment_reference: Optional[str]
    paystack_subscription_code: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_plan(cls, sub) -> "SubscriptionOut":
        return cls(
            id=sub.id, plan_id=sub.plan_id,
            plan_name=sub.plan.name if sub.plan else "",
            interval=sub.plan.interval if sub.plan else PlanInterval.MONTHLY,
            status=sub.status, units=sub.units,
            units_used=sub.units_used, units_remaining=sub.units_remaining,
            amount=sub.amount_paid, subscribed_at=sub.subscribed_at,
            renews_at=sub.renews_at, payment_reference=sub.payment_reference,
            paystack_subscription_code=sub.paystack_subscription_code,
            created_at=sub.created_at,
        )


class UsageMergeItem(BaseModel):
    subscription_id: UUID
    units: int = Field(..., gt=0)


class UsageRecordRequest(BaseModel):
    user_id: UUID
    units_used: int                = Field(..., gt=0)
    payment_method: UsagePaymentSource = UsagePaymentSource.SUBSCRIPTION
    subscription_id: Optional[UUID] = None
    sub_allocations: Optional[List[UsageMergeItem]] = None  # for merged deductions
    order_id: Optional[UUID]        = None
    order_reference: Optional[str] = None
    description: Optional[str]     = None
    notes: Optional[str]           = None
    payment_amount: Optional[Decimal] = None   # for direct payment records


class CustomerUsageLogOut(BaseModel):
    id: UUID
    user_id: UUID
    subscription_id: Optional[UUID]
    order_id: Optional[UUID]
    units_deducted: int
    source: UsagePaymentSource
    plan_name: Optional[str]
    description: Optional[str]
    balance_before: int
    balance_after: int
    total_units_snapshot: int
    is_merged: bool
    merge_breakdown: Optional[list]
    payment_amount: Optional[Decimal]
    created_at: datetime
    usernames: Optional[str] = None
    user_username: Optional[str] = None
    recorded_by_name: Optional[str] = None

    model_config = {"from_attributes": True}


class CustomerUsageStatsOut(BaseModel):
    total_units: int
    units_used: int
    remaining_units: int
    usage_percentage: float
    subscriptions: List[SubscriptionOut]

