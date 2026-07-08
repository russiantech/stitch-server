# # app/services/payment_providers/opay_provider.py
# """
# OPay Merchant API adapter.

# OPay's API differs from Paystack structurally: authentication uses a
# MerchantId + PublicKey/PrivateKey pair (HMAC-signed requests, not a
# Bearer secret key), and split settlement is called "Sub-Merchant" or
# handled via their Payment Split API depending on integration tier.

# This is a functional skeleton — the exact endpoint paths and payload
# shape must be confirmed against OPay's current merchant API docs
# (https://documentation.opaycheckout.com) once you have live sandbox
# credentials, since a few fields here are placeholders pending that
# confirmation. Do not deploy this against production without validating
# each request/response shape against a sandbox transaction first.
# """
# import hashlib
# import hmac
# import logging
# from decimal import Decimal
# from typing import Any, Dict, Optional

# import httpx

# from app.core.config import get_app_config
# from app.services.payments.base import PaymentProviderBase, PaymentProviderError
# from app.utils.helpers import to_kobo

# logger = logging.getLogger(__name__)


# class OpayService(PaymentProviderBase):
#     name = "opay"
#     BASE = "https://liveapi.opaycheckout.com/api/v1"  # sandbox: https://testapi.opaycheckout.com/api/v1
#     TIMEOUT = 30

#     def __init__(self):
#         cfg = get_app_config().payments_config.opay
#         self._merchant_id = cfg.merchant_id or ""
#         self._public_key = cfg.public_key or ""
#         self._secret_key = cfg.secret_key or ""

#     def _ensure_configured(self):
#         if not self._merchant_id or not self._public_key or not self._secret_key:
#             raise PaymentProviderError(
#                 "OPay is not yet configured on this server. Set APP_OPAY_MERCHANT_ID, "
#                 "APP_OPAY_PUBLIC_KEY, and APP_OPAY_SECRET_KEY, or choose a different provider.",
#                 503,
#             )

#     def _sign(self, payload: dict) -> str:
#         import json
#         body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
#         return hmac.new(self._secret_key.encode(), body.encode(), hashlib.sha512).hexdigest()

#     def _headers(self, payload: dict) -> Dict[str, str]:
#         self._ensure_configured()
#         return {
#             "Authorization": f"Bearer {self._public_key}",
#             "MerchantId": self._merchant_id,
#             "Content-Type": "application/json",
#             "Signature": self._sign(payload),
#         }

#     # def _post(self, path: str, payload: dict) -> dict:
#     #     url = f"{self.BASE}{path}"
#     #     try:
#     #         r = httpx.post(url, json=payload, headers=self._headers(payload), timeout=self.TIMEOUT)
#     #         data = r.json()
#     #         if data.get("code") != "00000":
#     #             raise PaymentProviderError(data.get("message", "OPay error"), r.status_code, data)
#     #         return data
#     #     except httpx.RequestError as exc:
#     #         raise PaymentProviderError(f"Network error: {exc}", 502)
    
#     def _post(self, path: str, payload: dict) -> dict:
#         url = f"{self.BASE}{path}"
#         try:
#             r = httpx.post(url, json=payload, headers=self._headers(payload), timeout=self.TIMEOUT)
#         except httpx.RequestError as exc:
#             raise PaymentProviderError(f"Network error: {exc}", 502)

#         try:
#             data = r.json()
#         except ValueError:
#             logger.error("OPay returned non-JSON response (%s) for %s: %s", r.status_code, path, r.text[:500])
#             raise PaymentProviderError(
#                 f"OPay returned an unexpected response (HTTP {r.status_code}). "
#                 f"This usually means the endpoint path is wrong or not yet available.",
#                 r.status_code,
#             )

#         if r.status_code == 404:
#             logger.error("OPay endpoint not found: %s — check the API path against current OPay docs.", url)
#             raise PaymentProviderError(f"OPay endpoint not found: {path}. This integration path needs to be verified against OPay's actual API.", 404)

#         if data.get("code") != "00000":
#             raise PaymentProviderError(data.get("message") or f"OPay error (HTTP {r.status_code})", r.status_code, data)

#         return data

#     def initialize_transaction(self, email, amount, reference, callback_url=None, metadata=None,
#                                 subaccount_code=None, channels=None) -> dict:
#         payload: Dict[str, Any] = {
#             "reference": reference,
#             "amount": {"total": to_kobo(amount), "currency": "NGN"},
#             "returnUrl": callback_url,
#             "callbackUrl": callback_url,
#             "userInfo": {"userEmail": email},
#             "productList": [{"name": "Stitch order", "quantity": 1, "price": to_kobo(amount)}],
#         }
#         if subaccount_code:
#             # OPay's split model: confirm exact field name against their
#             # Payment Split API docs before relying on this in production.
#             payload["paymentSplit"] = [{"merchantId": subaccount_code}]
#         data = self._post("/international/cashier/create", payload)
#         d = data.get("data", {})
#         return {
#             "authorization_url": d.get("cashierUrl"),
#             "access_code": d.get("orderNo") or reference,
#             "reference": reference,
#         }

#     def verify_transaction(self, reference: str) -> dict:
#         data = self._post("/international/cashier/status", {"reference": reference})
#         return data.get("data", {})

#     def create_subaccount(self, business_name, bank_code, account_number, percentage_charge) -> dict:
#         # OPay sub-merchant onboarding is typically a separate KYC-driven
#         # flow (not a simple API call like Paystack's) — likely requires
#         # their business onboarding portal or a dedicated sub-merchant
#         # creation endpoint. Placeholder until confirmed with OPay directly.
#         raise NotImplementedError(
#             "OPay sub-merchant creation requires their business onboarding "
#             "flow — confirm exact API with OPay before enabling this provider."
#         )

#     def resolve_account_number(self, account_number: str, bank_code: str) -> dict:
#         data = self._post("/payment/account/validate", {"accountNumber": account_number, "bankCode": bank_code})
#         d = data.get("data", {})
#         return {"account_name": d.get("accountName"), "account_number": account_number}

#     def list_banks(self) -> list:
#         data = self._post("/payment/banks", {})
#         return [{"name": b.get("name"), "code": b.get("code")} for b in data.get("data", [])]

#     def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
#         expected = hmac.new(self._secret_key.encode(), body, hashlib.sha512).hexdigest()
#         return hmac.compare_digest(expected, signature)


# v2
"""app/services/payments/opay.py — OPay Checkout API integration.

Confirmed against https://documentation.opaycheckout.com/ (Payment
Authentication, API Signature, Cashier Create, Query Payment Status).

IMPORTANT: OPay's public Checkout API covers payment collection only
(initialize/verify). It does NOT expose a subaccount, split-payment,
bank-list, or account-resolve endpoint anywhere in this documentation.
create_subaccount / resolve_account_number / list_banks therefore raise
a clear PaymentProviderError rather than guessing at endpoints — if
OPay offers a separate Payout/Sub-Merchant product, it will need to be
requested from their business support and integrated separately.
"""
import hashlib
import hmac
import json
import logging
from decimal import Decimal
from typing import Any, Dict, Optional

import httpx

from app.core.config import get_app_config
from app.services.payments.base import PaymentProviderBase, PaymentProviderError
from app.utils.helpers import to_kobo

logger = logging.getLogger(__name__)


class OpayService(PaymentProviderBase):
    name = "opay"
    LIVE_BASE = "https://liveapi.opaycheckout.com/api/v1"
    TEST_BASE = "https://testapi.opaycheckout.com/api/v1"
    TIMEOUT = 30

    def __init__(self):
        cfg = get_app_config().payments_config.opay
        self._merchant_id = cfg.merchant_id or ""
        self._public_key = cfg.public_key or ""
        self._secret_key = cfg.secret_key or ""
        self._sandbox = getattr(cfg, "sandbox", True)
        self.BASE = self.TEST_BASE if self._sandbox else self.LIVE_BASE

    def _ensure_configured(self):
        if not self._merchant_id or not self._public_key or not self._secret_key:
            raise PaymentProviderError(
                "OPay is not yet configured on this server. Set APP_OPAY_MERCHANT_ID, "
                "APP_OPAY_PUBLIC_KEY, and APP_OPAY_SECRET_KEY, or choose a different provider.",
                503,
            )

    @staticmethod
    def _sorted_json(payload: dict) -> str:
        # OPay requires the payload sorted alphabetically by key (nested
        # keys included) before signing/sending — json.dumps(sort_keys=True)
        # sorts recursively, matching the TreeMap behavior in OPay's own
        # Java sample code.
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)

    def _sign(self, payload: dict) -> str:
        body = self._sorted_json(payload)
        return hmac.new(self._secret_key.encode(), body.encode(), hashlib.sha512).hexdigest()

    def _post(self, path: str, payload: dict, auth: str) -> dict:
        """auth='public' → Cashier Create (Bearer PublicKey).
        auth='signature' → Cashier Status/Refund/etc (Bearer HMAC-SHA512)."""
        self._ensure_configured()
        bearer = self._public_key if auth == "public" else self._sign(payload)
        headers = {
            "Authorization": f"Bearer {bearer}",
            "MerchantId": self._merchant_id,
            "Content-Type": "application/json",
        }
        url = f"{self.BASE}{path}"
        body = self._sorted_json(payload)

        try:
            r = httpx.post(url, content=body, headers=headers, timeout=self.TIMEOUT)
        except httpx.RequestError as exc:
            raise PaymentProviderError(f"Network error contacting OPay: {exc}", 502)

        try:
            data = r.json()
        except ValueError:
            logger.error("OPay non-JSON response (%s) for %s: %s", r.status_code, path, r.text[:500])
            raise PaymentProviderError(
                f"OPay returned an unexpected response (HTTP {r.status_code}) for {path}.",
                r.status_code,
            )

        if data.get("code") != "00000":
            raise PaymentProviderError(
                data.get("message") or f"OPay error (HTTP {r.status_code})", r.status_code, data,
            )
        return data

    # ── Payment collection ──────────────────────────────────────────────────

    def initialize_transaction(
        self, email: str, amount: Decimal, reference: str,
        callback_url: Optional[str] = None, metadata: Optional[dict] = None,
        subaccount_code: Optional[str] = None, channels: Optional[list] = None,
    ) -> dict:
        if subaccount_code:
            logger.warning(
                "OPay has no split-payment endpoint in the public Checkout API — "
                "subaccount_code was supplied but will be ignored for reference %s.",
                reference,
            )
        payload: Dict[str, Any] = {
            "country": "NG",
            "reference": reference,
            "amount": {"total": to_kobo(amount), "currency": "NGN"},
            "returnUrl": callback_url or "",
            "callbackUrl": callback_url or "",
            "userInfo": {"userEmail": email},
            "product": {"name": "Stitch payment", "description": "Stitch order/subscription payment"},
        }
        data = self._post("/international/cashier/create", payload, auth="public")
        d = data.get("data", {})
        return {
            "authorization_url": d.get("cashierUrl"),
            "access_code": d.get("orderNo"),
            "reference": d.get("reference", reference),
        }

    def verify_transaction(self, reference: str) -> dict:
        payload = {"reference": reference, "country": "NG"}
        data = self._post("/international/cashier/status", payload, auth="signature")
        d = data.get("data", {})
        # Normalize to the same shape callers already expect from Paystack's
        # verify_transaction, so downstream code (from_kobo, status checks)
        # doesn't need provider-specific branching.
        return {
            "status": "success" if d.get("status") == "SUCCESS" else (d.get("status") or "").lower(),
            "amount": d.get("amount", {}).get("total", 0),
            "id": d.get("orderNo"),
            "channel": None,
            "authorization": None,
        }

    # ── Not available via the public Checkout API ───────────────────────────

    def create_subaccount(self, business_name: str, bank_code: str, account_number: str, percentage_charge: float) -> dict:
        raise PaymentProviderError(
            "OPay's public Checkout API does not offer a subaccount/split-payment endpoint. "
            "Contact OPay's business support for their Payout or Sub-Merchant API.",
            501,
        )

    def resolve_account_number(self, account_number: str, bank_code: str) -> dict:
        raise PaymentProviderError(
            "OPay's public Checkout API does not offer an account-resolve endpoint.",
            501,
        )

    def list_banks(self) -> list:
        raise PaymentProviderError(
            "OPay's public Checkout API does not offer a bank-list endpoint.",
            501,
        )

    # ── Webhook verification ────────────────────────────────────────────────

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        # Uses the same HMAC-SHA512 signing primitive documented for API
        # calls. If webhook verification ever fails unexpectedly, check
        # https://documentation.opaycheckout.com/callback-signature — the
        # callback signing scheme wasn't independently re-verified here.
        try:
            payload = json.loads(body)
        except ValueError:
            return False
        expected = self._sign(payload)
        return hmac.compare_digest(expected, signature)

