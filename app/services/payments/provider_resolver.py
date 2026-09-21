# # app/services/payments/provider_resolver.py
# """app/services/payments/provider_resolver.py — Resolves which payment
# provider (and subaccount, if any) a given organization should use for a
# transaction. Centralizes the org → provider → subaccount lookup so every
# payment-initiating call site stays consistent."""
# from dataclasses import dataclass
# from typing import Optional

# from sqlalchemy.orm import Session

# from app.models.organization import Organization
# from app.models.payments.providers import TenantProviderAccount
# from app.services.payments import get_provider
# from app.services.payments.base import PaymentProviderBase

# DEFAULT_FALLBACK_PROVIDER = "paystack"


# @dataclass
# class ResolvedProvider:
#     client: PaymentProviderBase
#     provider_name: str
#     subaccount_code: Optional[str]


# def _get_provider_for_org(db: Session, organization_id: Optional[str]) -> ResolvedProvider:
#     """
#     Looks up the organization's preferred payment provider and, if they've
#     completed payout setup, their active subaccount code for that provider.

#     Falls back to Paystack with no subaccount (platform absorbs 100% —
#     i.e. an un-split payment) if:
#       - organization_id is None (e.g. a user with no org yet), or
#       - the org has no active TenantProviderAccount for their preferred
#         provider (payout not configured yet).

#     This fallback is intentional and safe for subscription payments (paid
#     TO the platform, not split), but for order payments this means the
#     tenant's share won't be split out — callers handling customer-facing
#     order payments should treat an unconfigured payout as a state to
#     surface to the tenant, not silently swallow.
#     """
#     provider_name = DEFAULT_FALLBACK_PROVIDER
#     subaccount_code: Optional[str] = None

#     if organization_id:
#         org = db.get(Organization, organization_id)
#         if org:
#             provider_name = org.preferred_provider or DEFAULT_FALLBACK_PROVIDER
#             account = db.query(TenantProviderAccount).filter(
#                 TenantProviderAccount.organization_id == organization_id,
#                 TenantProviderAccount.provider == provider_name,
#                 TenantProviderAccount.is_active == True,  # noqa: E712
#             ).first()
#             if account:
#                 subaccount_code = account.subaccount_code

#     return ResolvedProvider(
#         client=get_provider(provider_name),
#         provider_name=provider_name,
#         subaccount_code=subaccount_code,
#     )




# # v2
# """app/services/payments/provider_resolver.py — Resolves which payment
# provider (and subaccount, if any) a given organization should use, and keeps
# checkout working when a stored subaccount doesn't belong to the current keys."""
# import hashlib
# import logging
# from dataclasses import dataclass
# from typing import Optional

# from sqlalchemy.orm import Session

# from app.core.config import get_app_config
# from app.core.exceptions.custom_exceptions import CustomAPIException
# from app.models.organization import Organization
# from app.models.payments.providers import TenantProviderAccount
# from app.services.payments import get_provider
# from app.services.payments.base import PaymentProviderBase, PaymentProviderError

# logger = logging.getLogger(__name__)

# DEFAULT_FALLBACK_PROVIDER = "paystack"

# # What to do when Paystack rejects a tenant's stored subaccount:
# #   True  -> take the payment un-split and flag it ("split_skipped") so it can be
# #            reconciled. Checkout never breaks.
# #   False -> fail with 409 PAYOUT_ACCOUNT_INVALID.
# ALLOW_UNSPLIT_FALLBACK = True

# # Turns on automatically once the key_fingerprint column exists (Step 4).
# _HAS_FINGERPRINT = hasattr(TenantProviderAccount, "key_fingerprint")


# @dataclass
# class ResolvedProvider:
#     client: PaymentProviderBase
#     provider_name: str
#     subaccount_code: Optional[str]
#     # Added with defaults so existing constructions/reads keep working.
#     account: Optional[TenantProviderAccount] = None
#     split_skipped_reason: Optional[str] = None


# def key_fingerprint(provider_name: str = DEFAULT_FALLBACK_PROVIDER) -> str:
#     """'live:1a2b3c4d5e', 'test:...' or 'unconfigured'. Derived from the active
#     secret key; safe to log and store. Paystack only."""
#     if provider_name != "paystack":
#         return "unconfigured"
#     cfg = getattr(get_app_config().payments_config, "paystack", None)
#     secret = getattr(cfg, "secret_key", None) or ""
#     if not secret:
#         return "unconfigured"
#     mode = "test" if secret.startswith("sk_test_") else "live" if secret.startswith("sk_live_") else "unknown"
#     return f"{mode}:{hashlib.sha256(secret.encode()).hexdigest()[:10]}"


# def _get_provider_for_org(db: Session, organization_id: Optional[str]) -> ResolvedProvider:
#     """
#         Looks up the organization's preferred payment provider and, if they've
#         completed payout setup, their active subaccount code for that provider.

#         Falls back to Paystack with no subaccount (platform absorbs 100% —
#         i.e. an un-split payment) if:
#         - organization_id is None (e.g. a user with no org yet), or
#         - the org has no active TenantProviderAccount for their preferred
#             provider (payout not configured yet).

#         This fallback is intentional and safe for subscription payments (paid
#         TO the platform, not split), but for order payments this means the
#         tenant's share won't be split out — callers handling customer-facing
#         order payments should treat an unconfigured payout as a state to
#         surface to the tenant, not silently swallow.
#     """
#     provider_name = DEFAULT_FALLBACK_PROVIDER
#     subaccount_code: Optional[str] = None
#     account: Optional[TenantProviderAccount] = None
#     skipped: Optional[str] = None
#     key_fingerprint: Optional[str] = None
    
#     if organization_id:
#         org = db.get(Organization, organization_id)
#         if org:
#             provider_name = org.preferred_provider or DEFAULT_FALLBACK_PROVIDER
#             account = db.query(TenantProviderAccount).filter(
#                 TenantProviderAccount.organization_id == organization_id,
#                 TenantProviderAccount.provider == provider_name,
#                 TenantProviderAccount.is_active == True,  # noqa: E712
#             ).first()
#             if account:
#                 stored = getattr(account, "key_fingerprint", None) if _HAS_FINGERPRINT else None
#                 current = key_fingerprint(provider_name)
#                 if stored and current != "unconfigured" and stored != current:
#                     skipped = "key_set_changed"
#                     logger.warning(
#                         "Org %s subaccount was linked under key set %s but the active set is %s; "
#                         "not sending it.", organization_id, stored, current,
#                     )
#                 else:
#                     subaccount_code = account.subaccount_code
#                     # account.subaccount_code = account["subaccount_code"]
#                     key_fingerprint = key_fingerprint("paystack") if provider_name == "paystack" else None

#     return ResolvedProvider(
#         client=get_provider(provider_name),
#         provider_name=provider_name,
#         subaccount_code=subaccount_code,
#         key_fingerprint=key_fingerprint,
#         account=account,
#         split_skipped_reason=skipped,
#     )


# # ─── Recovery ────────────────────────────────────────────────────────────────

# def _is_bad_subaccount(exc: Exception) -> bool:
#     return "subaccount" in (getattr(exc, "message", None) or str(exc)).lower()


# def _flag(tx_kwargs: dict, reason: str) -> dict:
#     return {**tx_kwargs, "metadata": {**(tx_kwargs.get("metadata") or {}), "split_skipped": reason}}


# def _payout_invalid() -> CustomAPIException:
#     return CustomAPIException(
#         "This business's payout account isn't valid for the current payment "
#         "configuration. Please re-link the payout account and try again.",
#         409, "PAYOUT_ACCOUNT_INVALID",
#     )


# def _stamp_fingerprint(db: Session, resolved: ResolvedProvider) -> None:
#     """A legacy row (no fingerprint) whose code Paystack just accepted is proven
#     valid under the current live keys, so label it. Never allowed to break a payment."""
#     account = resolved.account
#     if not (_HAS_FINGERPRINT and account and resolved.subaccount_code
#             and resolved.provider_name == "paystack"):
#         return
#     if getattr(account, "key_fingerprint", None):
#         return
#     fp = key_fingerprint("paystack")
#     if not fp.startswith("live:"):
#         return  # test keys never send the subaccount (see _is_test_mode), so nothing was validated
#     try:
#         with db.begin_nested():
#             account.key_fingerprint = fp
#     except Exception:
#         logger.exception("Could not stamp key fingerprint for org=%s", account.organization_id)


# def initialize_with_recovery(db: Session, resolved: ResolvedProvider, **tx_kwargs) -> dict:
#     """Drop-in for resolved.client.initialize_transaction(...). Do NOT pass
#     subaccount_code; it comes from `resolved`.

#     Happy path is identical to the old call. If the stored subaccount is known
#     or found to be invalid, the payment is either taken un-split and flagged, or
#     rejected with a 409, depending on ALLOW_UNSPLIT_FALLBACK."""
#     code = resolved.subaccount_code

#     if resolved.split_skipped_reason:  # decided up front: key set changed
#         if not ALLOW_UNSPLIT_FALLBACK:
#             raise _payout_invalid()
#         tx_kwargs = _flag(tx_kwargs, resolved.split_skipped_reason)

#     try:
#         tx = resolved.client.initialize_transaction(subaccount_code=code, **tx_kwargs)
#     except PaymentProviderError as exc:
#         if not (code and resolved.provider_name == "paystack" and _is_bad_subaccount(exc)):
#             raise
#         logger.error(
#             "Paystack rejected subaccount %s under key set %s: %s",
#             code, key_fingerprint("paystack"), getattr(exc, "message", exc),
#         )
#         if not ALLOW_UNSPLIT_FALLBACK:
#             raise _payout_invalid() from exc
#         resolved.subaccount_code = None
#         resolved.split_skipped_reason = "subaccount_rejected"
#         return resolved.client.initialize_transaction(
#             subaccount_code=None, **_flag(tx_kwargs, "subaccount_rejected")
#         )

#     _stamp_fingerprint(db, resolved)
#     return tx



# v3
"""app/services/payments/provider_resolver.py — Resolves which payment
provider (and subaccount, if any) an organization should use, and rebuilds the
subaccount automatically when it doesn't belong to the currently configured keys."""
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import get_app_config
from app.core.exceptions.custom_exceptions import CustomAPIException
from app.models.organization import Organization
from app.models.payments.providers import TenantProviderAccount
from app.services.payments import get_provider
from app.services.payments.base import PaymentProviderBase, PaymentProviderError

logger = logging.getLogger(__name__)

DEFAULT_FALLBACK_PROVIDER = "paystack"

# Last resort, only used when the subaccount can't be rebuilt:
#   True  -> take the payment un-split and flag it ("split_skipped") for manual settlement
#   False -> fail with 409 PAYOUT_ACCOUNT_INVALID
ALLOW_UNSPLIT_FALLBACK = True

_HAS_FINGERPRINT = hasattr(TenantProviderAccount, "key_fingerprint")


@dataclass
class ResolvedProvider:
    client: PaymentProviderBase
    provider_name: str
    subaccount_code: Optional[str]
    # Added with defaults so existing constructions/reads keep working.
    account: Optional[TenantProviderAccount] = None
    org: Optional[Organization] = None
    needs_relink: bool = False
    split_skipped_reason: Optional[str] = None


def key_fingerprint(provider_name: str = DEFAULT_FALLBACK_PROVIDER) -> str:
    """'live:<hash>', 'test:<hash>' or 'unconfigured'. Safe to log and store."""
    if provider_name != "paystack":
        return "unconfigured"
    cfg = getattr(get_app_config().payments_config, "paystack", None)
    secret = getattr(cfg, "secret_key", None) or ""
    if not secret:
        return "unconfigured"
    mode = "test" if secret.startswith("sk_test_") else "live" if secret.startswith("sk_live_") else "unknown"
    return f"{mode}:{hashlib.sha256(secret.encode()).hexdigest()[:10]}"


def _percentage_charge(org: Organization) -> float:
    # MUST match setup_payout in payouts.py (see the note about this convention below).
    return 100 - float(org.platform_fee_percent)


def _get_provider_for_org(db: Session, organization_id: Optional[str]) -> ResolvedProvider:
    # (keep your existing docstring here)
    provider_name = DEFAULT_FALLBACK_PROVIDER
    subaccount_code: Optional[str] = None
    account: Optional[TenantProviderAccount] = None
    org: Optional[Organization] = None
    needs_relink = False

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
                stored = getattr(account, "key_fingerprint", None) if _HAS_FINGERPRINT else None
                current = key_fingerprint(provider_name)
                if stored and current != "unconfigured" and stored != current:
                    needs_relink = True

    return ResolvedProvider(
        client=get_provider(provider_name),
        provider_name=provider_name,
        subaccount_code=subaccount_code,
        account=account,
        org=org,
        needs_relink=needs_relink,
    )


# ─── Recovery ────────────────────────────────────────────────────────────────

def _is_bad_subaccount(exc: Exception) -> bool:
    return "subaccount" in (getattr(exc, "message", None) or str(exc)).lower()


def _flag(tx_kwargs: dict, reason: str) -> dict:
    return {**tx_kwargs, "metadata": {**(tx_kwargs.get("metadata") or {}), "split_skipped": reason}}


def _payout_invalid() -> CustomAPIException:
    return CustomAPIException(
        "This business's payout account isn't valid for the current payment "
        "configuration. Please re-link the payout account and try again.",
        409, "PAYOUT_ACCOUNT_INVALID",
    )


# def relink_subaccount(db: Session, resolved: ResolvedProvider) -> Optional[str]:
#     """Recreate (or reuse) the tenant's subaccount on the CURRENT Paystack account
#     from the payout details stored on the Organization. Commits on success.
#     Returns the new code, or None if it can't be done. Never raises."""
#     org, account, client = resolved.org, resolved.account, resolved.client
#     if resolved.provider_name != "paystack" or not (org and account):
#         return None
#     if not (org.payout_bank_code and org.payout_account_number and org.platform_fee_percent is not None):
#         logger.warning("Org %s has no stored payout details; cannot relink.", org.id)
#         return None
#     try:
#         code = None
#         finder = getattr(client, "find_subaccount", None)
#         if finder:
#             found = finder(org.payout_account_number, org.name)
#             if found:
#                 code = found.get("subaccount_code")
#                 if code:
#                     try:  # keep the split percentage in line with the org's setting
#                         client.update_subaccount(code, percentage_charge=_percentage_charge(org))
#                     except Exception:
#                         logger.warning("Could not update percentage on reused subaccount %s", code)
#         if not code:
#             data = client.create_subaccount(
#                 business_name=org.name,
#                 bank_code=org.payout_bank_code,
#                 account_number=org.payout_account_number,
#                 percentage_charge=_percentage_charge(org),
#             )
#             code = (data or {}).get("subaccount_code")
#         if not code:
#             return None

#         account.subaccount_code = code
#         account.is_active = True
#         account.verified_at = datetime.now(timezone.utc)
#         if _HAS_FINGERPRINT:
#             account.key_fingerprint = key_fingerprint("paystack")
#         db.commit()
#         logger.info("Relinked subaccount for org=%s under key set %s", org.id, key_fingerprint("paystack"))
#         return code
#     except Exception:
#         db.rollback()
#         logger.exception("Subaccount relink failed for org=%s", getattr(org, "id", None))
#         return None

# v2
def relink_subaccount(db: Session, resolved: ResolvedProvider) -> Optional[str]:
    """Recreate (or reuse) the tenant's subaccount on the CURRENT Paystack account
    from the payout details stored on the Organization. Returns the new code, or
    None if it can't be done. Never raises.

    Does NOT commit or roll back the caller's transaction: some call sites (e.g.
    initiate_subscription) have already flushed a Payment row, and a commit here
    would persist it early while a rollback would wipe it. The change rides on the
    caller's normal commit; scripts must commit themselves. If the request later
    fails, the DB link is rolled back but the Paystack-side subaccount remains, and
    find_subaccount() reuses it next time."""
    org, account, client = resolved.org, resolved.account, resolved.client
    if resolved.provider_name != "paystack" or not (org and account):
        return None
    if not (org.payout_bank_code and org.payout_account_number and org.platform_fee_percent is not None):
        logger.warning("Org %s has no stored payout details; cannot relink.", org.id)
        return None
    try:
        code = None
        finder = getattr(client, "find_subaccount", None)
        if finder:
            found = finder(org.payout_account_number, org.name)
            if found:
                code = found.get("subaccount_code")
                if code:
                    try:  # keep the split percentage in line with the org's setting
                        client.update_subaccount(code, percentage_charge=_percentage_charge(org))
                    except Exception:
                        logger.warning("Could not update percentage on reused subaccount %s", code)
        if not code:
            data = client.create_subaccount(
                business_name=org.name,
                bank_code=org.payout_bank_code,
                account_number=org.payout_account_number,
                percentage_charge=_percentage_charge(org),
            )
            code = (data or {}).get("subaccount_code")
        if not code:
            return None
    except Exception:
        logger.exception("Subaccount relink failed for org=%s", getattr(org, "id", None))
        return None

    try:
        with db.begin_nested():  # savepoint: a failure here can't touch the caller's work
            account.subaccount_code = code
            account.is_active = True
            account.verified_at = datetime.now(timezone.utc)
            if _HAS_FINGERPRINT:
                account.key_fingerprint = key_fingerprint("paystack")
    except Exception:
        logger.exception("Could not save relinked subaccount for org=%s", org.id)
        return None

    logger.info("Relinked subaccount for org=%s under key set %s", org.id, key_fingerprint("paystack"))
    return code


def _stamp_fingerprint(db: Session, resolved: ResolvedProvider) -> None:
    """Legacy row (no fingerprint) whose code Paystack just accepted under LIVE
    keys is proven valid there, so label it. Never allowed to break a payment."""
    account = resolved.account
    if not (_HAS_FINGERPRINT and account and resolved.subaccount_code
            and resolved.provider_name == "paystack"):
        return
    if getattr(account, "key_fingerprint", None):
        return
    fp = key_fingerprint("paystack")
    if not fp.startswith("live:"):
        return  # test keys never send the subaccount, so nothing was validated
    try:
        with db.begin_nested():
            account.key_fingerprint = fp
    except Exception:
        logger.exception("Could not stamp key fingerprint for org=%s", account.organization_id)


def _without_split(resolved: ResolvedProvider, tx_kwargs: dict, reason: str, cause: Optional[Exception] = None):
    if not ALLOW_UNSPLIT_FALLBACK:
        raise _payout_invalid() from cause
    resolved.subaccount_code = None
    resolved.split_skipped_reason = reason
    return resolved.client.initialize_transaction(subaccount_code=None, **_flag(tx_kwargs, reason))


def initialize_with_recovery(db: Session, resolved: ResolvedProvider, **tx_kwargs) -> dict:
    """Drop-in for resolved.client.initialize_transaction(...). Do NOT pass
    subaccount_code; it comes from `resolved`.

    1. Fingerprint says the code belongs to another key set -> rebuild first.
    2. Legacy row rejected by Paystack -> rebuild once and retry with the split.
    3. Can't rebuild -> un-split + flagged, or 409 (ALLOW_UNSPLIT_FALLBACK).
    Happy path is identical to the old call."""
    client = resolved.client
    is_paystack = resolved.provider_name == "paystack"
    live = key_fingerprint("paystack").startswith("live:")
    code = resolved.subaccount_code

    if is_paystack and live and resolved.needs_relink:
        code = relink_subaccount(db, resolved)
        if not code:
            return _without_split(resolved, tx_kwargs, "key_set_changed")
        resolved.subaccount_code = code
        resolved.needs_relink = False

    try:
        tx = client.initialize_transaction(subaccount_code=code, **tx_kwargs)
    except PaymentProviderError as exc:
        if not (code and is_paystack and _is_bad_subaccount(exc)):
            raise
        logger.error("Paystack rejected subaccount %s under key set %s: %s",
                     code, key_fingerprint("paystack"), getattr(exc, "message", exc))
        new_code = relink_subaccount(db, resolved)
        if new_code and new_code != code:
            resolved.subaccount_code = new_code
            return client.initialize_transaction(subaccount_code=new_code, **tx_kwargs)
        return _without_split(resolved, tx_kwargs, "subaccount_rejected", exc)

    _stamp_fingerprint(db, resolved)
    return tx

