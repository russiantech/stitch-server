"""app/models/pricing.py — GarmentType, LaundryService, DeliveryArea."""
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

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

