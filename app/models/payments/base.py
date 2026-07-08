"""app/models/payments.py — Payment transactions and Paystack webhook events."""
from datetime import datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
import uuid

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.base import StitchBase, TenantModel
from app.enums.stitch import PaymentStatus, PaymentProvider, PaymentPurpose

if TYPE_CHECKING:
    from app.models.users import User
    from app.models.orders import Order
    from app.models.tenant_billing import CustomerSubscription
    from app.models.platform_billing import PlatformInvoice
    from app.models.organization import Organization


class Payment(TenantModel, Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_payments_user_id", "user_id"),
        Index("ix_payments_reference", "reference"),
        Index("ix_payments_status", "status"),
        Index("ix_payments_org_id", "organization_id"),
        Index("ix_payments_invoice_id", "platform_invoice_id"),
    )

    user_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    order_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL")
    )
    # Tenant-level: customer paying organization for a service plan
    customer_subscription_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_subscriptions.id", ondelete="SET NULL")
    )
    # Platform-level: organization paying Stitch (you)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    platform_invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_invoices.id", ondelete="SET NULL")
    )

    reference: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    provider: Mapped[PaymentProvider] = mapped_column(
        Enum(PaymentProvider), default=PaymentProvider.PAYSTACK
    )
    purpose: Mapped[PaymentPurpose] = mapped_column(
        Enum(PaymentPurpose), default=PaymentPurpose.ORDER
    )
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus), default=PaymentStatus.PENDING
    )
    currency: Mapped[str] = mapped_column(String(10), default="NGN")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    amount_paid: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))

    # Paystack-specific
    paystack_id: Mapped[Optional[str]] = mapped_column(String(255))
    access_code: Mapped[Optional[str]] = mapped_column(String(255))
    authorization_url: Mapped[Optional[str]] = mapped_column(Text)
    channel: Mapped[Optional[str]] = mapped_column(String(50))
    card_type: Mapped[Optional[str]] = mapped_column(String(50))
    bank: Mapped[Optional[str]] = mapped_column(String(100))
    last4: Mapped[Optional[str]] = mapped_column(String(10))
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="payments")
    order: Mapped[Optional["Order"]] = relationship("Order", back_populates="payments")
    customer_subscription: Mapped[Optional["CustomerSubscription"]] = relationship(
        "CustomerSubscription", back_populates="payments"
    )
    
    organization: Mapped[Optional["Organization"]] = relationship("Organization")
    platform_invoice: Mapped[Optional["PlatformInvoice"]] = relationship(
        "PlatformInvoice", back_populates="payments"
    )

    def __repr__(self) -> str:
        return f"<Payment id={self.id} ref={self.reference!r} status={self.status} amount={self.amount}>"


class PaystackWebhookEvent(TenantModel, Base):
    """Raw Paystack webhook events — for idempotency and audit."""
    __tablename__ = "paystack_webhook_events"

    # id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    reference: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    processed: Mapped[bool] = mapped_column(default=False, nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error: Mapped[Optional[str]] = mapped_column(Text)

    def __repr__(self) -> str:
        return (
            f"<PaystackWebhookEvent id={self.id} event_id={self.event_id!r} "
            f"type={self.event_type!r} processed={self.processed}>"
        )

