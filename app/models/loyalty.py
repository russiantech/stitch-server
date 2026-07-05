"""app/models/loyalty.py — LoyaltyTransaction for points tracking."""
from typing import Optional, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.db.database import Base
from app.models.base import  TenantModel
from app.enums.stitch import LoyaltyAction

if TYPE_CHECKING:
    from app.models.users import User


class LoyaltyTransaction(TenantModel, Base):
    __tablename__ = "loyalty_transactions"
    __table_args__ = (Index("ix_loyalty_user", "user_id"),)
    
    user_id: Mapped[UUID]              = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[LoyaltyAction]     = mapped_column(Enum(LoyaltyAction), nullable=False)
    points: Mapped[int]               = mapped_column(Integer, nullable=False)   # positive=earn, negative=redeem
    balance_after: Mapped[int]        = mapped_column(Integer, nullable=False)
    reference: Mapped[Optional[str]]  = mapped_column(String(255))   # order ref / reason code
    description: Mapped[Optional[str]] = mapped_column(Text)
    awarded_by_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))

    user: Mapped["User"]                    = relationship("User", foreign_keys=[user_id], back_populates="loyalty_transactions")
    # awarded_by: Mapped[Optional["User"]]    = relationship("User", foreign_keys=[awarded_by_id])
    awarded_by: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[awarded_by_id], back_populates="awarded_loyalty"
    )

