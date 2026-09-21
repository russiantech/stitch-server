# app/api/v1/payouts.py
"""app/api/v1/payouts.py — Tenant payout configuration: bank details, subaccounts."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps.auth import require_admin
from app.core.exceptions.custom_exceptions import BadRequestError, CustomAPIException
from app.db.database import get_db
from app.models.organization import Organization
from app.models.payments.providers import TenantProviderAccount
from app.models.users import User
from app.schemas.payouts import BankResolveRequest, PayoutSetupRequest
from app.services.payments import get_provider, PaymentProviderError
from app.services.payments.provider_resolver import key_fingerprint
from app.utils.responses import api_response

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Payouts"])


# @router.get("/banks")
# def list_banks(
#     provider: str = "opay",
#     admin: User = Depends(require_admin),
# ):
#     try:
#         banks = get_provider(provider).list_banks()
#     except PaymentProviderError as exc:
#         raise CustomAPIException(f"Could not fetch banks: {exc.message}", 502)
#     return api_response(True, "Banks fetched.", data=banks)

@router.get("/banks")
def list_banks(provider: str = "paystack", admin: User = Depends(require_admin)):
    try:
        banks = get_provider(provider).list_banks()
    except PaymentProviderError as exc:
        raise CustomAPIException(f"Could not fetch banks: {exc.message}", exc.status_code or 502)
    return api_response(True, "Banks fetched.", data=banks)

@router.post("/resolve-account")
def resolve_account(
    payload: BankResolveRequest,
    admin: User = Depends(require_admin),
):
    try:
        result = get_provider(payload.provider).resolve_account_number(
            payload.account_number, payload.bank_code
        )
    except PaymentProviderError as exc:
        raise BadRequestError(f"Could not verify account: {exc.message}", exc.status_code or 502)
    return api_response(True, "Account resolved.", data=result)


@router.post("/setup")
def setup_payout(
    payload: PayoutSetupRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter(Organization.id == admin.organization_id).first()
    if not org:
        raise BadRequestError("Organization not found.")

    provider_client = get_provider(payload.provider)

    # Re-verify the account before creating the subaccount — never trust
    # client-submitted account_name; always derive it from the provider.
    try:
        resolved = provider_client.resolve_account_number(payload.account_number, payload.bank_code)
    except PaymentProviderError as exc:
        raise BadRequestError(f"Could not verify account: {exc.message}", exc.status_code or 502)

    tenant_share = 100 - float(payload.platform_fee_percent)
    try:
        sub = provider_client.create_subaccount(
            business_name=org.name,
            bank_code=payload.bank_code,
            account_number=payload.account_number,
            percentage_charge=tenant_share,
        )
    except PaymentProviderError as exc:
        raise CustomAPIException(f"Could not create payout account: {exc.message}", exc.status_code or 502)

    existing = db.query(TenantProviderAccount).filter(
        TenantProviderAccount.organization_id == org.id,
        TenantProviderAccount.provider == payload.provider,
    ).first()

    # if existing:
    #     existing.subaccount_code = sub.get("subaccount_code", "")
    #     existing.key_fingerprint = sub.get("key_fingerprint")
    #     existing.verified_at = datetime.now(timezone.utc)
    #     existing.is_active = True
    # else:
    #     db.add(TenantProviderAccount(
    #         organization_id=org.id,
    #         provider=payload.provider,
    #         subaccount_code=sub.get("subaccount_code", ""),
    #         verified_at=datetime.now(timezone.utc),
    #     ))
    
    # v2
    fp = key_fingerprint(payload.provider)  # "unconfigured" for non-Paystack providers
    if existing:
        existing.subaccount_code = sub.get("subaccount_code", "")
        existing.verified_at = datetime.now(timezone.utc)
        existing.is_active = True
        existing.key_fingerprint = fp
    else:
        acct = TenantProviderAccount(
            organization_id=org.id,
            provider=payload.provider,
            subaccount_code=sub.get("subaccount_code", ""),
            verified_at=datetime.now(timezone.utc),
            key_fingerprint = fp
        )
        db.add(acct)

    org.preferred_provider = payload.provider
    org.payout_bank_code = payload.bank_code
    org.payout_account_number = payload.account_number
    org.payout_account_name = resolved.get("account_name")
    org.platform_fee_percent = payload.platform_fee_percent
    org.payout_configured_at = datetime.now(timezone.utc)

    db.commit()
    logger.info("Payout configured for org %s via %s", org.id, payload.provider)

    return api_response(True, "Payout account configured.", data={
        "provider": payload.provider,
        "account_name": org.payout_account_name,
        "account_number": org.payout_account_number,
    })


@router.get("/status")
def payout_status(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter(Organization.id == admin.organization_id).first()
    if not org:
        raise BadRequestError("Organization not found.")
    return api_response(True, "Payout status fetched.", data={
        "configured": bool(org.payout_configured_at),
        "provider": org.preferred_provider,
        "account_name": org.payout_account_name,
        "account_number": org.payout_account_number,
        "bank_code": org.payout_bank_code,
        "platform_fee_percent": float(org.platform_fee_percent),
        "settlement_schedule": org.settlement_schedule,
    })

