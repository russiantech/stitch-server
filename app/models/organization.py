"""
app/models/organization.py — Organization (tenant) model.

Uses StitchBase (not TenantModel) because Organization is the tenant
root — it cannot be scoped to itself.
"""

from datetime import datetime
from decimal import Decimal
import uuid
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
import secrets

from app.db.database import Base
from app.models.base import StitchBase
from app.models.platform_billing import OrganizationSubscription

if TYPE_CHECKING:
    from app.models.users import User
    from app.models.payments.providers import TenantProviderAccount


class Organization(StitchBase, Base):

    __tablename__ = "organizations"

    # ── Identity ──────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(60), unique=True, index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # ── Plan / limits ─────────────────────────────────────────────────────
    plan: Mapped[str] = mapped_column(String(20), default="free", nullable=False)
    # free | starter | pro | enterprise
    max_users: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    max_products: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    # ── Feature flags ─────────────────────────────────────────────────────
    allow_public_signup: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    invite_code: Mapped[Optional[str]] = mapped_column(
        String(20), unique=True, nullable=True, index=True
    )


    # ── Billing ───────────────────────────────────────────────────────────
    subscription_status: Mapped[str] = mapped_column(
        String(20), default="trialing", nullable=False
    )
    # trialing | active | past_due | canceled
    subscription_ends_at: Mapped[Optional[DateTime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    
    # ── Payout configuration ─────────────────────────────────────────────
    preferred_provider: Mapped[str] = mapped_column(String(20), default="opay", nullable=False)
    payout_bank_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    payout_account_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    payout_account_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # Paystack-verified name
    platform_fee_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"), nullable=False)
    settlement_schedule: Mapped[str] = mapped_column(String(20), default="auto", nullable=False, )  # "auto" only for now
    payout_configured_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Per-provider subaccount codes (a tenant may have one per provider
    #    they've connected — most will only ever use their default) ──────
    provider_accounts: Mapped[List["TenantProviderAccount"]] = relationship(
        "TenantProviderAccount", back_populates="organization", cascade="all, delete-orphan"
    )

    # ── Ownership ─────────────────────────────────────────────────────────
    # Set to the first user's id after that row is flushed in signup_verify.
    # use_alter breaks the circular FK: organizations ↔ users.
    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", use_alter=True, name="fk_org_owner_id"),
        nullable=True,
    )

    # ── Relationships ─────────────────────────────────────────────────────
    owner: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[owner_id],
        back_populates="owned_organization",
    )
    users: Mapped[list["User"]] = relationship(
        "User",
        back_populates="organization",
        foreign_keys="User.organization_id",
    )
    
    platform_subscription: Mapped[Optional["OrganizationSubscription"]] = relationship(
        "OrganizationSubscription",
        back_populates="organization",
        uselist=False,
    )

    # ── Helpers ───────────────────────────────────────────────────────────
    
    
    @staticmethod
    def generate_invite_code() -> str:
        """8-char alphanumeric code, uppercase. Readable, not guessable.
        Example: DUNTECH8, STITCH2X
        Avoids O/0 and I/1 confusion."""
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(secrets.choice(alphabet) for _ in range(8))

    def get_summary(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "slug": self.slug,
            "plan": self.plan,
            "max_users": self.max_users,
            "max_products": self.max_products,
            "description": self.description,
            "allow_public_signup": self.allow_public_signup,
            "is_active": self.is_active,
            "is_paused": self.is_paused,
            "subscription_status": self.subscription_status,
            "subscription_ends_at": (
                self.subscription_ends_at.isoformat() if self.subscription_ends_at else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<Organization id={self.id} slug={self.slug!r} plan={self.plan!r}>"