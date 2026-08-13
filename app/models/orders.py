# v2
"""
app/models/orders.py — Order, LaundryOrder, FashionOrder, history, line items.
Single Order table (polymorphic) + type-specific extension tables.
"""

from datetime import date
import datetime
from decimal import Decimal
from typing import List, Optional, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean, Date, Enum, ForeignKey, Integer,
    Numeric, String, Text, JSON, Index, DateTime,  
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.base import StitchBase, TenantModel
from app.enums.stitch import (
    OrderType, OrderPriority, PaymentMethodType,
    LaundryStatus, FashionStatus, FashionServiceType,
)

if TYPE_CHECKING:
    from app.models.users import User
    from app.models.payments.base import Payment
    from app.models.pricing import DeliveryArea, GarmentType
    from app.models.tenant_billing import CustomerSubscription


class Order(TenantModel, Base):
    __tablename__ = "orders"

    __table_args__ = (
        Index("ix_orders_customer", "customer_id"),
        Index("ix_orders_type_status", "order_type", "status"),
        Index("ix_orders_behalf_user", "behalf_user_id"),
    )

    reference: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    order_type: Mapped[OrderType] = mapped_column(Enum(OrderType), nullable=False)

    customer_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    behalf_user_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    pickup_date: Mapped[Optional[date]] = mapped_column(Date)
    pickup_time: Mapped[Optional[str]] = mapped_column(String(50))
    delivery_date: Mapped[Optional[date]] = mapped_column(Date)

    delivery_area_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("delivery_areas.id", ondelete="SET NULL")
    )
    delivery_address: Mapped[Optional[str]] = mapped_column(Text)

    garment_subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    priority_surcharge: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)

    payment_method: Mapped[PaymentMethodType] = mapped_column(
        Enum(PaymentMethodType), default=PaymentMethodType.DIRECT
    )
    payment_status: Mapped[str] = mapped_column(String(30), default="unpaid")
    payment_reference: Mapped[Optional[str]] = mapped_column(String(255))

    # Tenant-level subscription (customer paying organization)
    customer_subscription_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("customer_subscriptions.id", ondelete="SET NULL")
    )

    priority: Mapped[OrderPriority] = mapped_column(
        Enum(OrderPriority), default=OrderPriority.NORMAL
    )
    special_instructions: Mapped[Optional[str]] = mapped_column(Text)
    internal_notes: Mapped[Optional[str]] = mapped_column(Text)

    assigned_driver_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    assigned_staff_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    status: Mapped[str] = mapped_column(String(50), nullable=False)

    customer: Mapped["User"] = relationship(
        "User", foreign_keys=[customer_id], back_populates="orders"
    )
    behalf_user: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[behalf_user_id], back_populates="orders_on_behalf"
    )
    created_by: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[created_by_id], back_populates="orders_created"
    )
    driver: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[assigned_driver_id], back_populates="deliveries"
    )
    staff: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[assigned_staff_id], back_populates="assigned_orders"
    )
    delivery_area: Mapped[Optional["DeliveryArea"]] = relationship("DeliveryArea")
    customer_subscription: Mapped[Optional["CustomerSubscription"]] = relationship(
        "CustomerSubscription"
    )

    status_history: Mapped[List["OrderStatusHistory"]] = relationship(
        "OrderStatusHistory", back_populates="order", cascade="all, delete-orphan",
        order_by="OrderStatusHistory.created_at"
    )
    garment_items: Mapped[List["OrderGarmentItem"]] = relationship(
        "OrderGarmentItem", back_populates="order", cascade="all, delete-orphan"
    )
    payments: Mapped[List["Payment"]] = relationship("Payment", back_populates="order")
    laundry_detail: Mapped[Optional["LaundryOrder"]] = relationship(
        "LaundryOrder", back_populates="order", uselist=False
    )
    fashion_detail: Mapped[Optional["FashionOrder"]] = relationship(
        "FashionOrder", back_populates="order", uselist=False
    )

    def __repr__(self) -> str:
        return f"<Order id={self.id} ref={self.reference!r} type={self.order_type} status={self.status!r}>"


class LaundryOrder(TenantModel, Base):
    __tablename__ = "laundry_orders"

    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    laundry_status: Mapped[LaundryStatus] = mapped_column(
        Enum(LaundryStatus), default=LaundryStatus.RECEIVED, nullable=False
    )
    garment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    services_json: Mapped[Optional[dict]] = mapped_column(JSON)
    is_express: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    order: Mapped["Order"] = relationship(
        "Order", back_populates="laundry_detail", foreign_keys=[order_id]
    )


class FashionOrder(TenantModel, Base):
    __tablename__ = "fashion_orders"

    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    fashion_status: Mapped[FashionStatus] = mapped_column(
        Enum(FashionStatus), default=FashionStatus.CONSULTATION, nullable=False
    )
    # service_type: Mapped[FashionServiceType] = mapped_column(
    #     Enum(FashionServiceType), nullable=False
    # )
    # FashionOrder model — replace service_type with:
    service_types: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    fabric_source: Mapped[str] = mapped_column(String(30), default="customer")
    measurements: Mapped[Optional[dict]] = mapped_column(JSON)
    design_notes: Mapped[Optional[str]] = mapped_column(Text)
    reference_images: Mapped[Optional[list]] = mapped_column(JSON)
    consultation_date: Mapped[Optional[date]] = mapped_column(Date)
    # app/models/orders.py — FashionOrder additions
    consultation_time: Mapped[Optional[str]] = mapped_column(String(30))
    consultation_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"), nullable=False)
    material_pickup_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"), nullable=False)
    fitting_date: Mapped[Optional[date]] = mapped_column(Date)

    order: Mapped["Order"] = relationship(
        "Order", back_populates="fashion_detail", foreign_keys=[order_id]
    )


class OrderStatusHistory(TenantModel, Base):
    """Immutable log of every status transition."""
    __tablename__ = "order_status_history"

    __table_args__ = (Index("ix_osh_order_id", "order_id"),)
    
    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[Optional[str]] = mapped_column(String(50))
    to_status: Mapped[str] = mapped_column(String(50), nullable=False)
    changed_by_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)
    is_reversal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    order: Mapped["Order"] = relationship("Order", back_populates="status_history")
    changed_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[changed_by_id])


class OrderGarmentItem(TenantModel, Base):
    """Line items — each garment type / quantity in an order."""
    __tablename__ = "order_garment_items"

    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    garment_type_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("garment_types.id", ondelete="SET NULL")
    )
    garment_name: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(80))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    service_multiplier: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=1.0)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    custom_price_note: Mapped[Optional[str]] = mapped_column(String(255))

    order: Mapped["Order"] = relationship("Order", back_populates="garment_items")
    garment_type: Mapped[Optional["GarmentType"]] = relationship("GarmentType")



class OrderDriverRequest(TenantModel, Base):
    """Audit trail + workflow state for a driver requesting to handle an
    unassigned order. Kept separate from Order.assigned_driver_id so we
    retain history even after approval/rejection, and so multiple drivers
    can request the same order (only one gets approved)."""
    __tablename__ = "order_driver_requests"

    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    driver_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending | approved | rejected
    request_type: Mapped[str] = mapped_column(String(20), nullable=False)  # pickup | delivery
    reviewed_by_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    order: Mapped["Order"] = relationship("Order")
    driver: Mapped["User"] = relationship("User", foreign_keys=[driver_id])

