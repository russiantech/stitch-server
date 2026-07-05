"""app/models/inventory.py — InventoryItem and InventoryLog."""
from decimal import Decimal
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid import UUID
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.db.database import Base
from app.models.base import StitchBase
from app.enums.stitch import InventoryCategory, InventoryStatus, InventoryLogAction

if TYPE_CHECKING:
    from app.models.users import User


class InventoryItem(StitchBase, Base):
    __tablename__ = "inventory_items"

    name: Mapped[str]                   = mapped_column(String(200), nullable=False)
    category: Mapped[InventoryCategory] = mapped_column(Enum(InventoryCategory), nullable=False)
    quantity: Mapped[int]               = mapped_column(Integer, default=0, nullable=False)
    unit: Mapped[str]                   = mapped_column(String(30), nullable=False)   # kg / L / pcs / yards ...
    reorder_level: Mapped[int]          = mapped_column(Integer, default=0)
    unit_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    supplier: Mapped[Optional[str]]     = mapped_column(String(200))
    notes: Mapped[Optional[str]]        = mapped_column(Text)

    @property
    def status(self) -> InventoryStatus:
        if self.quantity == 0:
            return InventoryStatus.OUT_OF_STOCK
        if self.quantity <= self.reorder_level:
            return InventoryStatus.LOW_STOCK
        return InventoryStatus.IN_STOCK

    logs: Mapped[list] = relationship("InventoryLog", back_populates="item", cascade="all, delete-orphan")


class InventoryLog(StitchBase, Base):
    """Immutable audit trail for all stock movements."""
    __tablename__ = "inventory_logs"
    __table_args__ = (Index("ix_inv_logs_item", "item_id"),)

    item_id: Mapped[UUID]              = mapped_column(PGUUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[InventoryLogAction] = mapped_column(Enum(InventoryLogAction), nullable=False)
    quantity_change: Mapped[int]      = mapped_column(Integer, nullable=False)  # positive=restock, negative=deduct
    quantity_before: Mapped[int]      = mapped_column(Integer, nullable=False)
    quantity_after: Mapped[int]       = mapped_column(Integer, nullable=False)
    performed_by_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[Optional[str]]     = mapped_column(String(300))

    item: Mapped["InventoryItem"]           = relationship("InventoryItem", back_populates="logs")
    performed_by: Mapped[Optional["User"]]  = relationship("User", foreign_keys=[performed_by_id])
    
    
