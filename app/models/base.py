"""
app/models/base.py — Stitch model base classes.

Every model in the codebase inherits from exactly one of these two:

    StitchBase   — UUID pk, timestamps, soft-delete.
                   For platform-level models with no tenant scope:
                   Organization, Role, AuditLog.

    TenantModel  — Everything in StitchBase, plus organization_id.
                   For every business entity owned by a tenant:
                   User, Product, Sale, StockHistory, Expense, …

Usage
-----

    from app.db.database import Base
    from app.models.base import StitchBase, TenantModel

    class Organization(StitchBase, Base):
        __tablename__ = "organizations"
        ...

    class Product(TenantModel, Base):
        __tablename__ = "products"
        # organization_id is already here — don't redeclare it
        ...

Why two classes instead of one
-------------------------------
Organization cannot be scoped to itself. Every other model can.
Keeping the distinction explicit at the class level (not via an
optional kwarg or a flag) means there's no way to accidentally add
organization_id to Organization or forget it on Product.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class StitchBase:
    """
    Platform-level base: UUID pk + timestamps + soft-delete.

    Inherit when the model is NOT scoped to any organization
    (Organization itself, Role, permission tables, audit logs).
    """

    # ── Primary key ───────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )

    # ── Timestamps ────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )

    # ── Soft delete ───────────────────────────────────────────────────────
    # Named `deleted` (not `is_deleted`) to match every filter in the
    # codebase: `.filter(Model.deleted == False)`.
    deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Methods ───────────────────────────────────────────────────────────

    def soft_delete(self) -> None:
        self.deleted = True
        self.deleted_at = datetime.now(timezone.utc)

    def restore(self) -> None:
        """Undo a soft delete — for admin recovery flows."""
        self.deleted = False
        self.deleted_at = None

    def touch(self) -> None:
        """Explicitly bump updated_at — useful when mutating a child
        relationship and wanting the parent timestamp to reflect it."""
        self.updated_at = datetime.now(timezone.utc)


class TenantModel(StitchBase):
    """
    Tenant-scoped base: everything in StitchBase + organization_id.

    Inherit for any model that belongs to a specific organization.
    organization_id is always present, always indexed, and always
    references the same FK target — defined once here so it can never
    drift between tables.

    use_alter=True on the FK emits it as a post-CREATE ALTER TABLE,
    breaking the circular dependency between users ↔ organizations
    that would otherwise block table creation ordering.
    """

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_tenant_organization_id",
        ),
        nullable=True,
        index=True,
    )


__all__ = ["StitchBase", "TenantModel"]
