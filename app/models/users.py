"""
app/models/user.py — User and supporting models (Address, EmailToken, OAuthAccount).

Model decisions
---------------
- Role assignment is M2M via the `user_roles` association table. The old
  `role` enum column and `role_id` FK are removed — they were redundant
  with the relationship and caused conflicting sources of truth.
- `has_role()` / `role_names` / `is_admin` all derive from `self.roles`
  (the M2M relationship loaded with lazy="selectin") so they work without
  an extra query anywhere a User is already loaded.
- `password_hash` is the single source of truth; `set_password` /
  `check_password` write and read that column consistently.
- Address, EmailToken, OAuthAccount each declare their own integer `id`
  separately from StitchBase because they're sub-resources of User (not
  independently queried by UUID in the wild), and their `user_id` FK is
  a UUID matching the User.id type from StitchBase.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING

from app.enums.stitch import UserStatus
from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Enum as SAEnum

from app.db.database import Base
from app.models.base import TenantModel
from app.models.association_tables import user_roles
from app.core.security.auth import hash_password, verify_password

if TYPE_CHECKING:
    from app.models.rbac import Role
    from app.models.organization import Organization
    from app.models.orders import Order
    from app.enums.stitch import UserStatus

# ─────────────────────────────────────────────────────────────────────────
# User
# ─────────────────────────────────────────────────────────────────────────

class User(TenantModel, Base):
    """
    Uses TenantModel so organization_id is already present as an indexed
    UUID FK column. No need to declare it here — don't redeclare it.
    """
    __tablename__ = "users"

    __table_args__ = (
        UniqueConstraint("email",    name="uq_users_email"),
        UniqueConstraint("username", name="uq_users_username"),
    )

    # ── Identity ──────────────────────────────────────────────────────────
    names: Mapped[str]               = mapped_column(String(150), nullable=False)
    email: Mapped[str]               = mapped_column(String(255), nullable=False, index=True)
    username: Mapped[Optional[str]]  = mapped_column(String(60), nullable=True, index=True)
    phone: Mapped[Optional[str]]     = mapped_column(String(30), nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[Optional[str]]= mapped_column(String(512), nullable=True)
    bio: Mapped[Optional[str]]       = mapped_column(Text, nullable=True)
    ip: Mapped[Optional[str]]        = mapped_column(String(45), nullable=True)

    # ── Status ────────────────────────────────────────────────────────────
    # status: Mapped[str]            = mapped_column(String(30), default="active", nullable=False, index=True)
    # is_active: Mapped[bool]          = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_org_admin: Mapped[bool]       = mapped_column(Boolean, default=False, nullable=False)
    email_verified: Mapped[bool]     = mapped_column(Boolean, default=False, nullable=False)
    is_online: Mapped[bool]          = mapped_column(Boolean, default=False, nullable=False)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # status: Mapped[UserStatus] = mapped_column(
    #     SAEnum(UserStatus, name="user_status", native_enum=True),
    #     default=UserStatus.PENDING,
    #     server_default=UserStatus.PENDING.value,
    #     nullable=False,
    #     index=True,
    # )
    
    status: Mapped[UserStatus] = mapped_column(
        SAEnum(
            UserStatus,
            name="user_status",
            native_enum=True,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        default=UserStatus.PENDING,
        server_default=UserStatus.PENDING.value,
        nullable=False,
        index=True,
    )
        
    # ── Customer-specific ────────────────────────────────────────────────
    loyalty_points: Mapped[int]      = mapped_column(Integer, default=0, nullable=False)
    referral_code: Mapped[Optional[str]] = mapped_column(String(30), unique=True, nullable=True)
    referred_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    notifications: Mapped[List["Notification"]] = relationship(
        "Notification", back_populates="user", lazy="dynamic"
    )

    # ── Order relationships (disambiguated via primaryjoin + foreign_keys) ──
    orders: Mapped[List["Order"]] = relationship(
        "Order",
        primaryjoin="User.id == Order.customer_id",
        foreign_keys="Order.customer_id",
        back_populates="customer",
        lazy="dynamic",
    )
    orders_on_behalf: Mapped[List["Order"]] = relationship(
        "Order",
        primaryjoin="User.id == Order.behalf_user_id",
        foreign_keys="Order.behalf_user_id",
        back_populates="behalf_user",
        lazy="dynamic",
    )
    orders_created: Mapped[List["Order"]] = relationship(
        "Order",
        primaryjoin="User.id == Order.created_by_id",
        foreign_keys="Order.created_by_id",
        back_populates="created_by",
        lazy="dynamic",
    )
    deliveries: Mapped[List["Order"]] = relationship(
        "Order",
        primaryjoin="User.id == Order.assigned_driver_id",
        foreign_keys="Order.assigned_driver_id",
        back_populates="driver",
        lazy="dynamic",
    )
    assigned_orders: Mapped[List["Order"]] = relationship(
        "Order",
        primaryjoin="User.id == Order.assigned_staff_id",
        foreign_keys="Order.assigned_staff_id",
        back_populates="staff",
        lazy="dynamic",
    )

    # ── Subscription & Usage relationships ──────────────────────────────────
    # subscriptions: Mapped[List["Subscription"]] = relationship(
    #     "Subscription", back_populates="user", lazy="dynamic"
    # )
    # usage_logs: Mapped[List["UsageLog"]] = relationship(
    #     "UsageLog", foreign_keys="UsageLog.user_id", back_populates="user", lazy="dynamic"
    # )
    # usage_recorded: Mapped[List["UsageLog"]] = relationship(
    #     "UsageLog", foreign_keys="UsageLog.recorded_by_id", back_populates="recorded_by", lazy="dynamic"
    # )
    
    customer_subscriptions: Mapped[List["CustomerSubscription"]] = relationship(
    "CustomerSubscription", back_populates="user", lazy="dynamic"
    )

    # Add this if not already present
    customer_usage_logs: Mapped[List["CustomerUsageLog"]] = relationship(
        "CustomerUsageLog",
        primaryjoin="User.id == CustomerUsageLog.user_id",
        foreign_keys="CustomerUsageLog.user_id",
        back_populates="user",
        lazy="dynamic",
    )

    customer_usage_recorded: Mapped[List["CustomerUsageLog"]] = relationship(
        "CustomerUsageLog", foreign_keys="CustomerUsageLog.recorded_by_id", back_populates="recorded_by", lazy="dynamic"
    )
    
    payments: Mapped[List["Payment"]] = relationship(
        "Payment", back_populates="user", lazy="dynamic"
    )
    # loyalty_transactions: Mapped[List["LoyaltyTransaction"]] = relationship(
    # "LoyaltyTransaction", back_populates="user", lazy="dynamic"
    # )
    loyalty_transactions: Mapped[List["LoyaltyTransaction"]] = relationship(
        "LoyaltyTransaction",
        primaryjoin="User.id == LoyaltyTransaction.user_id",
        foreign_keys="LoyaltyTransaction.user_id",
        back_populates="user",
        lazy="dynamic",
    )
    awarded_loyalty: Mapped[List["LoyaltyTransaction"]] = relationship(
        "LoyaltyTransaction",
        primaryjoin="User.id == LoyaltyTransaction.awarded_by_id",
        foreign_keys="LoyaltyTransaction.awarded_by_id",
        back_populates="awarded_by",
        lazy="dynamic",
    )

    roles: Mapped[List["Role"]] = relationship(
        "Role",
        secondary=user_roles,
        back_populates="users",
        lazy="selectin",
    )
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization",
        foreign_keys="User.organization_id",
        back_populates="users",
    )
    owned_organization: Mapped[Optional["Organization"]] = relationship(
        "Organization",
        foreign_keys="Organization.owner_id",
        back_populates="owner",
    )
    addresses: Mapped[List["Address"]]      = relationship(
        "Address", back_populates="user", cascade="all, delete-orphan"
    )
    referrals: Mapped[List["User"]]         = relationship(
        "User", foreign_keys=[referred_by_id]
    )
    email_tokens: Mapped[List["EmailToken"]] = relationship(
        "EmailToken", back_populates="user", cascade="all, delete-orphan"
    )
    oauth_accounts: Mapped[List["OAuthAccount"]] = relationship(
        "OAuthAccount", back_populates="user", cascade="all, delete-orphan"
    )

    # ── Password helpers ──────────────────────────────────────────────────

    def set_password(self, password: str) -> None:
        if not password:
            raise ValueError("Password cannot be empty.")
        self.password_hash = hash_password(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return verify_password(password, self.password_hash)

    # ── Role helpers ──────────────────────────────────────────────────────

    @property
    def role_names(self) -> List[str]:
        """List of role name strings. Falls back to ['staff'] when the
        user has no roles yet (e.g. immediately after creation before
        the admin assigns roles)."""
        if not self.roles:
            return ["staff"]
        return [r.name for r in self.roles]

    @property
    def is_admin(self) -> bool:
        return any(r.name in ("admin", "super_admin") for r in (self.roles or []))

    def has_role(self, *role_names: str) -> bool:
        names_lower = {r.lower() for r in role_names}
        return any(r.name.lower() in names_lower for r in (self.roles or []))

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    # ── Display ───────────────────────────────────────────────────────────

    @property
    def display_name(self) -> str:
        return self.names or self.username or self.email.split("@")[0]

    def get_summary(self) -> dict:
        return {
            "id": str(self.id),
            "names": self.names,
            "username": self.username,
            "email": self.email,
            "phone": self.phone,
            "avatar_url": self.avatar_url,
            "bio": self.bio,
            "status": self.status.value if isinstance(self.status, UserStatus) else self.status,
            "is_org_admin": self.is_org_admin,
            "email_verified": self.email_verified,
            "roles": self.role_names,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r}>"


# ─────────────────────────────────────────────────────────────────────────
# Address
# ─────────────────────────────────────────────────────────────────────────

class Address(TenantModel, Base):
    """
    Own integer PK (not StitchBase UUID) — addresses are sub-resources
    of User, retrieved via relationship, never by standalone UUID lookup.
    user_id is UUID to match User.id (StitchBase gives User a UUID pk).
    """
    __tablename__ = "addresses"

    # id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str]              = mapped_column(String(60), nullable=False)
    address_line: Mapped[str]       = mapped_column(Text, nullable=False)
    area: Mapped[Optional[str]]     = mapped_column(String(120), nullable=True)
    city: Mapped[str]               = mapped_column(String(100), default="Lagos", nullable=False)
    state: Mapped[str]              = mapped_column(String(100), default="Lagos", nullable=False)
    country: Mapped[str]            = mapped_column(String(80), default="Nigeria", nullable=False)
    is_default: Mapped[bool]        = mapped_column(Boolean, default=False, nullable=False)
    latitude: Mapped[Optional[float]]  = mapped_column(nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="addresses")

    def __repr__(self) -> str:
        return f"<Address id={self.id} label={self.label!r} user_id={self.user_id}>"


# ─────────────────────────────────────────────────────────────────────────
# EmailToken
# ─────────────────────────────────────────────────────────────────────────

class EmailToken(TenantModel, Base):
    """
    OTP / signed tokens for email verification, password reset, invites.
    Integer PK — tokens are short-lived, high-volume, never UUID-queried.
    """
    __tablename__ = "email_tokens"

    # id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token: Mapped[str]              = mapped_column(String(512), nullable=False, index=True)
    token_type: Mapped[str]         = mapped_column(String(30), nullable=False)
    # verify | reset | invite
    expires_at: Mapped[datetime]    = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_used: Mapped[bool]           = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="email_tokens")

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at.replace(tzinfo=timezone.utc)

    def __repr__(self) -> str:
        return f"<EmailToken id={self.id} type={self.token_type!r} used={self.is_used}>"


# ─────────────────────────────────────────────────────────────────────────
# OAuthAccount
# ─────────────────────────────────────────────────────────────────────────

class OAuthAccount(TenantModel, Base):
    """Social login link — one per provider per user."""
    __tablename__ = "oauth_accounts"

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
    )

    # id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str]           = mapped_column(String(30), nullable=False)
    provider_user_id: Mapped[str]   = mapped_column(String(255), nullable=False)
    access_token: Mapped[Optional[str]]  = mapped_column(Text, nullable=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="oauth_accounts")

    def __repr__(self) -> str:
        return f"<OAuthAccount id={self.id} provider={self.provider!r} user_id={self.user_id}>"

