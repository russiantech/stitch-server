
# v2
"""app/models/platform_billing.py — Platform-level billing for the SaaS."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey, Integer, Numeric,
    String, Text, JSON, UniqueConstraint, Index, text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.base import StitchBase
from app.enums.billing import (
    BillingModel, BillingInterval, SubscriptionStatus,
    InvoiceStatus, AddOnCategory, MetricCategory, AddOnBillingModel,
)

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.payments import Payment

# ─────────────────────────────────────────────────────────────────────────
# SaaSPlan
# ─────────────────────────────────────────────────────────────────────────

class SaaSPlan(StitchBase, Base):
    __tablename__ = "saas_plans"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    billing_model: Mapped[BillingModel] = mapped_column(
        Enum(BillingModel, native_enum=False), default=BillingModel.FREE, nullable=False
    )

    price_monthly: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    price_yearly: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="NGN", nullable=False)

    max_users: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_products: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_warehouses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_orders_per_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_sms_per_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    storage_quota_mb: Mapped[int] = mapped_column(Integer, default=512, nullable=False)

    transaction_fee_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), nullable=False
    )
    transaction_fee_fixed: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    transaction_fee_cap: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    transaction_fee_floor: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)

    features: Mapped[Optional[dict]] = mapped_column(JSON)
    add_on_slugs: Mapped[Optional[list]] = mapped_column(JSON)

    paystack_plan_code_monthly: Mapped[Optional[str]] = mapped_column(String(100))
    paystack_plan_code_yearly: Mapped[Optional[str]] = mapped_column(String(100))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    subscriptions: Mapped[List["OrganizationSubscription"]] = relationship(
        "OrganizationSubscription", back_populates="plan"
    )
    usage_limits: Mapped[List["PlanUsageLimit"]] = relationship(
        "PlanUsageLimit", back_populates="plan", cascade="all, delete-orphan"
    )

    def get_summary(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "slug": self.slug,
            "billing_model": self.billing_model.value,
            "price_monthly": float(self.price_monthly),
            "price_yearly": float(self.price_yearly),
            "currency": self.currency,
            "limits": {
                "users": self.max_users,
                "products": self.max_products,
                "warehouses": self.max_warehouses,
                "orders_per_month": self.max_orders_per_month,
                "sms_per_month": self.max_sms_per_month,
                "storage_mb": self.storage_quota_mb,
            },
            "transaction_fees": {
                "percent": float(self.transaction_fee_percent),
                "fixed": float(self.transaction_fee_fixed),
                "cap": float(self.transaction_fee_cap) if self.transaction_fee_cap else None,
                "floor": float(self.transaction_fee_floor) if self.transaction_fee_floor else None,
            },
            "features": self.features or [],
            "add_ons": self.add_on_slugs or [],
            "is_free": self.billing_model == BillingModel.FREE,
        }


# ─────────────────────────────────────────────────────────────────────────
# OrganizationSubscription
# ─────────────────────────────────────────────────────────────────────────

class OrganizationSubscription(StitchBase, Base):
    __tablename__ = "organization_subscriptions"

    __table_args__ = (
        # FIX: Cast the enum column to text so string literals in the WHERE
        # clause are valid. Postgres rejects bare string literals when the
        # column is a native enum type — the cast tells it to compare as text.
        Index(
            "uq_org_sub_active",
            "organization_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending', 'trialing', 'active', 'past_due')"
            ),
        ),
        Index("ix_org_sub_org", "organization_id"),
        Index("ix_org_sub_status", "status"),
        Index("ix_org_sub_plan", "plan_id"),
        Index("ix_org_sub_period_end", "current_period_end"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("saas_plans.id", ondelete="RESTRICT"),
        nullable=False,
    )

    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, native_enum=False), default=SubscriptionStatus.PENDING, nullable=False
    )
    billing_interval: Mapped[BillingInterval] = mapped_column(
        Enum(BillingInterval, native_enum=False), default=BillingInterval.MONTHLY, nullable=False
    )

    current_period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    grace_period_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    paystack_customer_code: Mapped[Optional[str]] = mapped_column(String(100))
    paystack_subscription_code: Mapped[Optional[str]] = mapped_column(String(100))
    paystack_email_token: Mapped[Optional[str]] = mapped_column(String(255))
    pending_reference: Mapped[Optional[str]] = mapped_column(String(100))
    last_payment_reference: Mapped[Optional[str]] = mapped_column(String(100))

    orders_used_this_period: Mapped[int] = mapped_column(Integer, default=0)
    sms_used_this_period: Mapped[int] = mapped_column(Integer, default=0)
    storage_used_mb: Mapped[int] = mapped_column(Integer, default=0)

    base_amount_due: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    usage_overage_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    last_invoice_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    next_invoice_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="platform_subscription"
    )
    plan: Mapped["SaaSPlan"] = relationship("SaaSPlan", back_populates="subscriptions")
    add_ons: Mapped[List["OrganizationAddOn"]] = relationship(
        "OrganizationAddOn", back_populates="subscription", cascade="all, delete-orphan"
    )
    invoices: Mapped[List["PlatformInvoice"]] = relationship(
        "PlatformInvoice", back_populates="subscription"
    )

    @property
    def is_trial_active(self) -> bool:
        if self.status != SubscriptionStatus.TRIALING or not self.trial_ends_at:
            return False
        return datetime.now(timezone.utc) < self.trial_ends_at

    @property
    def is_in_grace_period(self) -> bool:
        if not self.grace_period_ends_at:
            return False
        return datetime.now(timezone.utc) < self.grace_period_ends_at

    @property
    def is_paid_and_active(self) -> bool:
        return self.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING)

    def get_summary(self) -> dict:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "plan": self.plan.get_summary() if self.plan else None,
            "status": self.status.value,
            "billing_interval": self.billing_interval.value,
            "current_period": {
                "start": self.current_period_start.isoformat() if self.current_period_start else None,
                "end": self.current_period_end.isoformat() if self.current_period_end else None,
            },
            "trial_ends_at": self.trial_ends_at.isoformat() if self.trial_ends_at else None,
            "grace_period_ends_at": self.grace_period_ends_at.isoformat() if self.grace_period_ends_at else None,
            "usage": {
                "orders": self.orders_used_this_period,
                "sms": self.sms_used_this_period,
                "storage_mb": self.storage_used_mb,
            },
            "amounts": {
                "base": float(self.base_amount_due),
                "overage": float(self.usage_overage_amount),
            },
            "auto_renew": self.auto_renew,
        }


# ─────────────────────────────────────────────────────────────────────────
# AddOn
# ─────────────────────────────────────────────────────────────────────────

class AddOn(StitchBase, Base):
    __tablename__ = "add_ons"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[AddOnCategory] = mapped_column(Enum(AddOnCategory, native_enum=False), nullable=False)

    billing_model: Mapped[AddOnBillingModel] = mapped_column(
        Enum(AddOnBillingModel, native_enum=False), default=AddOnBillingModel.FLAT, nullable=False
    )
    price_monthly: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    price_yearly: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="NGN", nullable=False)

    requires_plan_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("saas_plans.id", ondelete="SET NULL")
    )
    max_quantity_per_org: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    paystack_plan_code_monthly: Mapped[Optional[str]] = mapped_column(String(100))
    paystack_plan_code_yearly: Mapped[Optional[str]] = mapped_column(String(100))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_recommended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    required_plan: Mapped[Optional["SaaSPlan"]] = relationship(
        "SaaSPlan", foreign_keys=[requires_plan_id]
    )
    subscriptions: Mapped[List["OrganizationAddOn"]] = relationship(
        "OrganizationAddOn", back_populates="add_on"
    )


# ─────────────────────────────────────────────────────────────────────────
# OrganizationAddOn
# ─────────────────────────────────────────────────────────────────────────

class OrganizationAddOn(StitchBase, Base):
    __tablename__ = "organization_add_ons"

    __table_args__ = (
        UniqueConstraint("organization_id", "add_on_id", name="uq_org_addon"),
        Index("ix_org_addon_org", "organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    add_on_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("add_ons.id", ondelete="CASCADE"), nullable=False
    )
    subscription_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization_subscriptions.id", ondelete="SET NULL"),
    )

    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, native_enum=False), default=SubscriptionStatus.PENDING, nullable=False
    )

    current_period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    unit_price_override: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    paystack_subscription_code: Mapped[Optional[str]] = mapped_column(String(100))

    add_on: Mapped["AddOn"] = relationship("AddOn", back_populates="subscriptions")
    subscription: Mapped[Optional["OrganizationSubscription"]] = relationship(
        "OrganizationSubscription", back_populates="add_ons"
    )
    organization: Mapped["Organization"] = relationship("Organization")


# ─────────────────────────────────────────────────────────────────────────
# UsageMetric
# ─────────────────────────────────────────────────────────────────────────

class UsageMetric(Base):
    __tablename__ = "usage_metrics"

    code: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    unit_name: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[MetricCategory] = mapped_column(Enum(MetricCategory, native_enum=False), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    plan_limits: Mapped[List["PlanUsageLimit"]] = relationship(
        "PlanUsageLimit", back_populates="metric"
    )
    usage_records: Mapped[List["OrganizationUsageRecord"]] = relationship(
        "OrganizationUsageRecord", back_populates="metric"
    )


# ─────────────────────────────────────────────────────────────────────────
# PlanUsageLimit
# ─────────────────────────────────────────────────────────────────────────

class PlanUsageLimit(StitchBase, Base):
    __tablename__ = "plan_usage_limits"

    __table_args__ = (
        UniqueConstraint("plan_id", "metric_code", name="uq_plan_metric"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("saas_plans.id", ondelete="CASCADE"), nullable=False
    )
    metric_code: Mapped[str] = mapped_column(
        String(50), ForeignKey("usage_metrics.code", ondelete="CASCADE"), nullable=False
    )
    included_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    overage_price_per_unit: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), default=Decimal("0.0000"), nullable=False
    )
    hard_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    plan: Mapped["SaaSPlan"] = relationship("SaaSPlan", back_populates="usage_limits")
    metric: Mapped["UsageMetric"] = relationship("UsageMetric", back_populates="plan_limits")


# ─────────────────────────────────────────────────────────────────────────
# OrganizationUsageRecord
# ─────────────────────────────────────────────────────────────────────────

class OrganizationUsageRecord(StitchBase, Base):
    __tablename__ = "organization_usage_records"

    __table_args__ = (
        Index("ix_usage_record_org", "organization_id"),
        Index("ix_usage_record_period", "period_start", "period_end"),
        Index("ix_usage_record_metric", "metric_code"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    metric_code: Mapped[str] = mapped_column(
        String(50), ForeignKey("usage_metrics.code", ondelete="RESTRICT"), nullable=False
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount_included: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    amount_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    amount_overage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    overage_charges: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    is_invoiced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("platform_invoices.id", ondelete="SET NULL")
    )

    metric: Mapped["UsageMetric"] = relationship("UsageMetric", back_populates="usage_records")
    invoice: Mapped[Optional["PlatformInvoice"]] = relationship(
        "PlatformInvoice", back_populates="usage_records"
    )


# ─────────────────────────────────────────────────────────────────────────
# TransactionFeeRule
# ─────────────────────────────────────────────────────────────────────────

class TransactionFeeRule(StitchBase, Base):
    __tablename__ = "transaction_fee_rules"

    __table_args__ = (
        UniqueConstraint(
            "plan_id", "payment_method", "transaction_type",
            name="uq_fee_rule",
        ),
        Index("ix_fee_rule_plan", "plan_id"),
        Index("ix_fee_rule_active", "is_active", "effective_from", "effective_until"),
    )

    plan_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("saas_plans.id", ondelete="CASCADE"), nullable=True
    )
    payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)

    fee_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"), nullable=False)
    fee_fixed: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"), nullable=False)
    fee_cap: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    fee_floor: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    effective_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    plan: Mapped[Optional["SaaSPlan"]] = relationship("SaaSPlan")

    @staticmethod
    def calculate_fee(
        amount: Decimal,
        percent: Decimal,
        fixed: Decimal,
        cap: Optional[Decimal] = None,
        floor: Optional[Decimal] = None,
    ) -> Decimal:
        fee = (amount * (percent / Decimal("100"))) + fixed
        if floor is not None:
            fee = max(fee, floor)
        if cap is not None:
            fee = min(fee, cap)
        return fee.quantize(Decimal("0.01"))


# ─────────────────────────────────────────────────────────────────────────
# PlatformInvoice
# ─────────────────────────────────────────────────────────────────────────

class PlatformInvoice(StitchBase, Base):
    __tablename__ = "platform_invoices"

    __table_args__ = (
        Index("ix_invoice_org", "organization_id"),
        Index("ix_invoice_status", "status"),
        Index("ix_invoice_due", "due_date"),
        Index("ix_invoice_number", "invoice_number"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    subscription_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organization_subscriptions.id", ondelete="SET NULL")
    )

    invoice_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    line_items: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    base_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    add_ons_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    usage_overage_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    transaction_fees_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    balance_due: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, native_enum=False), default=InvoiceStatus.DRAFT, nullable=False
    )

    paystack_transaction_reference: Mapped[Optional[str]] = mapped_column(String(255))
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    subscription: Mapped[Optional["OrganizationSubscription"]] = relationship(
        "OrganizationSubscription", back_populates="invoices"
    )
    
    usage_records: Mapped[List["OrganizationUsageRecord"]] = relationship(
        "OrganizationUsageRecord", back_populates="invoice"
    )
    
    payments: Mapped[List["Payment"]] = relationship(
        "Payment", back_populates="platform_invoice"
    )

    def calculate_balance(self) -> None:
        self.balance_due = self.total_amount - self.amount_paid
        if self.balance_due <= 0 and self.status not in (
            InvoiceStatus.CANCELED,
            InvoiceStatus.PAID,
        ):
            self.status = (
                InvoiceStatus.PAID if self.balance_due == 0 else InvoiceStatus.PARTIAL
            )

