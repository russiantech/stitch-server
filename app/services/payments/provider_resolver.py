# app/services/payments/provider_resolver.py
"""app/services/payments/provider_resolver.py — Resolves which payment
provider (and subaccount, if any) a given organization should use for a
transaction. Centralizes the org → provider → subaccount lookup so every
payment-initiating call site stays consistent."""
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.payments.providers import TenantProviderAccount
from app.services.payments import get_provider
from app.services.payments.base import PaymentProviderBase

DEFAULT_FALLBACK_PROVIDER = "paystack"


@dataclass
class ResolvedProvider:
    client: PaymentProviderBase
    provider_name: str
    subaccount_code: Optional[str]


def _get_provider_for_org(db: Session, organization_id: Optional[str]) -> ResolvedProvider:
    """
    Looks up the organization's preferred payment provider and, if they've
    completed payout setup, their active subaccount code for that provider.

    Falls back to Paystack with no subaccount (platform absorbs 100% —
    i.e. an un-split payment) if:
      - organization_id is None (e.g. a user with no org yet), or
      - the org has no active TenantProviderAccount for their preferred
        provider (payout not configured yet).

    This fallback is intentional and safe for subscription payments (paid
    TO the platform, not split), but for order payments this means the
    tenant's share won't be split out — callers handling customer-facing
    order payments should treat an unconfigured payout as a state to
    surface to the tenant, not silently swallow.
    """
    provider_name = DEFAULT_FALLBACK_PROVIDER
    subaccount_code: Optional[str] = None

    if organization_id:
        org = db.get(Organization, organization_id)
        if org:
            provider_name = org.preferred_provider or DEFAULT_FALLBACK_PROVIDER
            account = db.query(TenantProviderAccount).filter(
                TenantProviderAccount.organization_id == organization_id,
                TenantProviderAccount.provider == provider_name,
                TenantProviderAccount.is_active == True,  # noqa: E712
            ).first()
            if account:
                subaccount_code = account.subaccount_code

    return ResolvedProvider(
        client=get_provider(provider_name),
        provider_name=provider_name,
        subaccount_code=subaccount_code,
    )

