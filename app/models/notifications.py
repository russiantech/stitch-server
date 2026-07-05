"""app/models/notifications.py — In-app notification records."""
from datetime import datetime
from typing import Optional, TYPE_CHECKING
import uuid

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, JSON, Index
from sqlalchemy.dialects.postgresql import UUID  # ← ADD THIS
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.base import TenantModel
from app.enums.stitch import NotificationType

if TYPE_CHECKING:
    from app.models.users import User


class Notification(TenantModel, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifs_user_unread", "user_id", "is_read"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),  # ← FIX: was uuid.UUID(as_uuid=True)
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str]                    = mapped_column(String(255), nullable=False)
    message: Mapped[str]                  = mapped_column(Text, nullable=False)
    type: Mapped[NotificationType]        = mapped_column(Enum(NotificationType), default=NotificationType.SYSTEM)
    is_read: Mapped[bool]                 = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[Optional[datetime]]   = mapped_column(DateTime(timezone=True))
    action_url: Mapped[Optional[str]]     = mapped_column(String(512))
    meta: Mapped[Optional[dict]]          = mapped_column(JSON)

    user: Mapped["User"] = relationship("User", back_populates="notifications")

