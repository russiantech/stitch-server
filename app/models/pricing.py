"""app/models/pricing.py — GarmentType, LaundryService, DeliveryArea."""
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Integer, Numeric, String, Text, JSON, UniqueConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.db.database import Base
from app.models.base import TenantModel


class GarmentType(TenantModel, Base):
    """Admin-managed garment pricing catalogue."""
    __tablename__ = "garment_types"

    name: Mapped[str]          = mapped_column(String(150), nullable=False)
    category: Mapped[str]      = mapped_column(String(80), nullable=False)     # Tops / Bottoms / Household ...
    base_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    unit: Mapped[str]          = mapped_column(String(50), default="per piece")
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool]    = mapped_column(Boolean, default=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0)


class LaundryService(TenantModel, Base):
    """Admin-managed laundry service types (Standard Wash, Dry Cleaning …)."""
    __tablename__ = "laundry_services"

    name: Mapped[str]               = mapped_column(String(150), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    price_multiplier: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=1.0, nullable=False)
    icon: Mapped[Optional[str]]     = mapped_column(String(60))    # fa-* class
    is_active: Mapped[bool]         = mapped_column(Boolean, default=True)
    display_order: Mapped[int]      = mapped_column(Integer, default=0)


class DeliveryArea(TenantModel, Base):
    """Admin-managed delivery zones and flat-rate fees."""
    __tablename__ = "delivery_areas"

    # id: Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str]          = mapped_column(String(150), nullable=False, unique=True)
    price: Mapped[Decimal]     = mapped_column(Numeric(10, 2), nullable=False)
    state: Mapped[str]         = mapped_column(String(100), default="Lagos")
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool]    = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)


# class FashionFeeSettings(TenantModel, Base):
#     """Per-organization configurable fashion fees — one row per org,
#     get-or-create on first access (same pattern as Organization.invite_code)."""
#     __tablename__ = "fashion_fee_settings"

#     consultation_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("3000.00"), nullable=False)
#     material_pickup_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("2500.00"), nullable=False)
#     consultation_fee_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
#     material_pickup_fee_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

# app/models/pricing.py — FashionFeeSettings, revised
class FashionFeeSettings(TenantModel, Base):
    __tablename__ = "fashion_fee_settings"

    consultation_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("3000.00"), nullable=False)
    consultation_fee_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # which service types trigger the consultation fee — empty list/None = applies to ALL
    consultation_applies_to: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    material_pickup_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("2500.00"), nullable=False)
    material_pickup_fee_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    material_pickup_applies_to: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)


# app/models/pricing.py — addition
class FashionService(TenantModel, Base):
    """Admin-managed fashion service catalogue — replaces the previous
    hardcoded FashionServiceType enum entirely. Each org can define its
    own set of fashion services (names, icons, ordering)."""
    __tablename__ = "fashion_services"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    icon: Mapped[Optional[str]] = mapped_column(String(60))  # fa-* class
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0)


# app/models/pricing.py — addition
class FashionServiceOverride(TenantModel, Base):
    """Lets an organization hide a specific GLOBAL default fashion service
    from their own catalog, without affecting any other org. Only ever
    references global defaults (fashion_service_id where the target row
    has organization_id IS NULL) — an org's own services don't need this,
    since they can just delete/deactivate those directly.

    Hiding none of the defaults = mixed view (defaults + org's own additions).
    Hiding all defaults = effectively "show only what we added ourselves."
    This one mechanism covers both behaviors requested, at the org's own
    discretion, per-service."""
    __tablename__ = "fashion_service_overrides"
    __table_args__ = (
        UniqueConstraint("organization_id", "fashion_service_id", name="uq_org_fashion_service_hide"),
    )
    # Already inherited
    # organization_id: Mapped[UUIDType] = mapped_column(
    #     PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    # )
    fashion_service_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fashion_services.id", ondelete="CASCADE"), nullable=False, index=True
    )

# 
# app/models/pricing.py — additions

class LaundryServiceOverride(TenantModel, Base):
    """Lets an org hide a specific GLOBAL default laundry service from its
    own catalog, without affecting any other org. Mirrors FashionServiceOverride."""
    __tablename__ = "laundry_service_overrides"
    __table_args__ = (
        UniqueConstraint("organization_id", "laundry_service_id", name="uq_org_laundry_service_hide"),
    )
    laundry_service_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("laundry_services.id", ondelete="CASCADE"), nullable=False, index=True
    )


class GarmentTypeOverride(TenantModel, Base):
    """Lets an org hide a specific GLOBAL default garment type from its
    own catalog, without affecting any other org."""
    __tablename__ = "garment_type_overrides"
    __table_args__ = (
        UniqueConstraint("organization_id", "garment_type_id", name="uq_org_garment_type_hide"),
    )
    garment_type_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("garment_types.id", ondelete="CASCADE"), nullable=False, index=True
    )


class DeliveryAreaOverride(TenantModel, Base):
    """Lets an org hide a specific GLOBAL default delivery area from its
    own catalog, without affecting any other org."""
    __tablename__ = "delivery_area_overrides"
    __table_args__ = (
        UniqueConstraint("organization_id", "delivery_area_id", name="uq_org_delivery_area_hide"),
    )
    delivery_area_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delivery_areas.id", ondelete="CASCADE"), nullable=False, index=True
    )
