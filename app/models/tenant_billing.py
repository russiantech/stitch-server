"""app/models/tenant_billing.py — Tenant-level billing: service plans & customer subscriptions."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean, Date, DateTime, Enum, ForeignKey, Integer, 
    Numeric, String, Text, JSON, UniqueConstraint, Index,
)
import uuid
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.base import StitchBase, TenantModel
from app.enums.stitch import PlanInterval, UsagePaymentSource
from app.enums.billing import SubscriptionStatus
from app.models.payments import Payment

if TYPE_CHECKING:
    from app.models.users import User
    from app.models.orders import Order
    from app.models.payments import Payment


# ─────────────────────────────────────────────────────────────────────────
# ServicePlan — plans created BY tenants FOR their customers
# ─────────────────────────────────────────────────────────────────────────

class ServicePlan(TenantModel, Base):
    __tablename__ = "service_plans"

    __table_args__ = (
        Index("ix_service_plan_org", "organization_id"),
        Index("ix_service_plan_active", "organization_id", "is_active"),
    )

    # TenantModel provides organization_id
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False)          # e.g. 30 garments
    interval: Mapped[PlanInterval] = mapped_column(
        Enum(PlanInterval), default=PlanInterval.MONTHLY, nullable=False
    )

    # Laundry / fashion specific
    service_type: Mapped[Optional[str]] = mapped_column(String(50), default="both")
    garment_types_included: Mapped[Optional[list]] = mapped_column(JSON)

    paystack_plan_code: Mapped[Optional[str]] = mapped_column(String(100), unique=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_popular: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    customer_subscriptions: Mapped[List["CustomerSubscription"]] = relationship(
        "CustomerSubscription", back_populates="plan"
    )

    def __repr__(self) -> str:
        return f"<ServicePlan id={self.id} name={self.name!r} amount={self.amount}>"


# ─────────────────────────────────────────────────────────────────────────
# CustomerSubscription — a user's subscription to a tenant's service plan
# ─────────────────────────────────────────────────────────────────────────

class CustomerSubscription(TenantModel, Base):
    __tablename__ = "customer_subscriptions"

    __table_args__ = (
        # Only one active subscription per (user, plan) at a time
        UniqueConstraint(
            "user_id", "plan_id", "status",
            name="uq_customer_sub_active", deferrable=True,
        ),
        Index("ix_customer_sub_user", "user_id"),
        Index("ix_customer_sub_status", "status"),
        Index("ix_customer_sub_org", "organization_id"),
    )

    # TenantModel provides organization_id
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("service_plans.id", ondelete="RESTRICT"), nullable=False
    )

    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus), default=SubscriptionStatus.PENDING, nullable=False
    )

    # Billing period
    subscribed_at: Mapped[date] = mapped_column(Date, nullable=False)
    renews_at: Mapped[Optional[date]] = mapped_column(Date)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Unit tracking
    units: Mapped[int] = mapped_column(Integer, nullable=False)
    units_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    @property
    def units_remaining(self) -> int:
        return max(0, self.units - self.units_used)

    # Payment meta
    payment_reference: Mapped[Optional[str]] = mapped_column(String(255))
    paystack_subscription_code: Mapped[Optional[str]] = mapped_column(String(100))
    paystack_email_token: Mapped[Optional[str]] = mapped_column(String(255))
    amount_paid: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))

    # Pay-as-you-go tracking
    is_pay_as_you_go: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_order_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    orders_this_period: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    payments: Mapped[List["Payment"]] = relationship(
    "Payment", back_populates="customer_subscription"
    )
    user: Mapped["User"] = relationship("User", back_populates="customer_subscriptions")
    plan: Mapped["ServicePlan"] = relationship("ServicePlan", back_populates="customer_subscriptions")
    customer_usage_logs: Mapped[List["CustomerUsageLog"]] = relationship(
        "CustomerUsageLog", back_populates="customer_subscription"
    )

    def top_up_reset(self, new_units: int, new_renews_at: date, payment_ref: str) -> None:
        """Apply a top-up: reset counters and restart billing period."""
        self.units = new_units
        self.units_used = 0
        self.subscribed_at = datetime.now(timezone.utc).date()
        self.renews_at = new_renews_at
        self.status = SubscriptionStatus.ACTIVE
        self.payment_reference = payment_ref
        self.cancelled_at = None
        self.orders_this_period = 0

    def __repr__(self) -> str:
        return (
            f"<CustomerSubscription id={self.id} user_id={self.user_id} "
            f"plan={self.plan_id} status={self.status} remaining={self.units_remaining}>"
        )


# ─────────────────────────────────────────────────────────────────────────
# CustomerUsageLog — immutable audit of unit deductions (renamed from UsageLog)
# ─────────────────────────────────────────────────────────────────────────

class CustomerUsageLog(StitchBase, Base):
    __tablename__ = "customer_usage_logs"

    __table_args__ = (
        Index("ix_cust_usage_user", "user_id"),
        Index("ix_cust_usage_order", "order_id"),
        Index("ix_cust_usage_subscription", "subscription_id"),
        Index("ix_cust_usage_created", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    subscription_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("customer_subscriptions.id", ondelete="SET NULL")
    )
    order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL")
    )
    recorded_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    units_deducted: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[UsagePaymentSource] = mapped_column(
        Enum(UsagePaymentSource), default=UsagePaymentSource.SUBSCRIPTION
    )
    plan_name: Mapped[Optional[str]] = mapped_column(String(100))   # snapshot
    description: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    balance_before: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    total_units_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)

    is_merged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    merge_breakdown: Mapped[Optional[list]] = mapped_column(JSON)

    payment_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))

    user: Mapped["User"] = relationship(
        "User", foreign_keys=[user_id], back_populates="customer_usage_logs"
    )
    recorded_by: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[recorded_by_id]
    )
    customer_subscription: Mapped[Optional["CustomerSubscription"]] = relationship(
        "CustomerSubscription", back_populates="customer_usage_logs"
    )
    order: Mapped[Optional["Order"]] = relationship("Order")

    def __repr__(self) -> str:
        return (
            f"<CustomerUsageLog id={self.id} user_id={self.user_id} "
            f"deducted={self.units_deducted} remaining={self.balance_after}>"
        )

