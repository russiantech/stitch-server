# app/models/payment_providers.py
"""app/models/payments/providers.py — Per-tenant, per-provider payout subaccounts."""
from datetime import datetime
from typing import Optional, TYPE_CHECKING
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.base import TenantModel

if TYPE_CHECKING:
    from app.models.organization import Organization


class TenantProviderAccount(TenantModel, Base):
    """Links an Organization to a payment provider's subaccount/merchant ID,
    so the split-payment mechanism knows where to route each transaction."""
    __tablename__ = "tenant_provider_accounts"

    __table_args__ = (
        UniqueConstraint("organization_id", "provider", name="uq_org_provider"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)  # matches PaymentProvider enum values
    subaccount_code: Mapped[str] = mapped_column(String(150), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    key_fingerprint: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    is_test_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="provider_accounts")

    def __repr__(self) -> str:
        return f"<TenantProviderAccount org={self.organization_id} provider={self.provider}>"

