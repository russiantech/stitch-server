"""
app/services/payments/paystack.py — Full Paystack v2 API integration for Stitch.
Handles: initialize, verify, subscriptions (create/cancel/pause/resume/manage-link),
charge authorization, refunds, and plan management.
"""
import hashlib
import hmac
import logging
from decimal import Decimal
import socket
from typing import Any, Dict, Optional

import httpx

from app.core.config import get_app_config
from app.utils.helpers import to_kobo
from app.services.payments.base import PaymentProviderBase

logger = logging.getLogger(__name__)


class PaystackError(Exception):
    def __init__(self, message: str, status_code: int = 400, raw: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.raw = raw or {}


# class PaystackService:
class PaystackService(PaymentProviderBase):
    name = "paystack"
    BASE = "https://api.paystack.co"
    TIMEOUT = 30

    def __init__(self):
        cfg = get_app_config().payments_config.paystack
        self._secret = cfg.secret_key or ""
        self._callback_url = cfg.callback_url or "http://localhost:5173/subscriptions?verify=1"

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._secret}",
            "Content-Type": "application/json",
        }

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.BASE}{path}"
        try:
            r = httpx.post(url, json=payload, headers=self._headers(), timeout=self.TIMEOUT)
            data = r.json()
            if not data.get("status"):
                raise PaystackError(data.get("message", "Paystack error"), r.status_code, data)
            return data
        except httpx.TimeoutException:
            raise PaystackError("Paystack request timed out", 504)
        except httpx.RequestError as exc:
            raise PaystackError(f"Network error: {exc}", 502)

    # app/services/payments/paystack.py — improved error messages
    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self.BASE}{path}"
        try:
            r = httpx.get(url, params=params or {}, headers=self._headers(), timeout=self.TIMEOUT)
            data = r.json()
            if not data.get("status"):
                raise PaystackError(data.get("message", "Paystack error"), r.status_code, data)
            return data
        except httpx.TimeoutException:
            raise PaystackError("Paystack request timed out. Please try again.", 504)
        except httpx.ConnectError as exc:
            if isinstance(exc.__cause__, socket.gaierror) or "getaddrinfo" in str(exc):
                raise PaystackError(
                    "Could not reach Paystack — this usually means a temporary network or DNS issue. Please try again in a moment.",
                    503,
                )
            raise PaystackError(f"Could not connect to Paystack: {exc}", 502)
        except httpx.RequestError as exc:
            raise PaystackError(f"Network error: {exc}", 502)
        
    def _put(self, path: str, payload: dict) -> dict:
        url = f"{self.BASE}{path}"
        r = httpx.put(url, json=payload, headers=self._headers(), timeout=self.TIMEOUT)
        data = r.json()
        if not data.get("status"):
            raise PaystackError(data.get("message", "Paystack error"), r.status_code, data)
        return data

    # ── Transaction ───────────────────────────────────────────────────────────

    # def initialize_transaction(
    #     self,
    #     email: str,
    #     amount: Decimal,
    #     reference: str,
    #     callback_url: Optional[str] = None,
    #     metadata: Optional[dict] = None,
    #     plan_code: Optional[str] = None,
    #     subaccount_code: Optional[str] = None,
    #     channels: Optional[list] = None,
    # ) -> dict:
    #     """
    #     Initialize a payment. If plan_code is supplied, Paystack sets up
    #     recurring billing automatically (for subscription top-ups).
    #     """
    #     payload: Dict[str, Any] = {
    #         "email": email,
    #         "amount": to_kobo(amount),
    #         "reference": reference,
    #         "currency": "NGN",
    #         "callback_url": callback_url or self._callback_url,
    #     }
    #     if metadata:
    #         payload["metadata"] = metadata
    #     if plan_code:
    #         payload["plan"] = plan_code   # ← Paystack recurring plan
    #     if channels:
    #         payload["channels"] = channels
    #     if subaccount_code:
    #         payload["subaccount"] = subaccount_code
    #         payload["bearer_type"] = "account"  # platform (you) absorbs the Paystack processing fee, not the tenant
    #     data = self._post("/transaction/initialize", payload)
        
    #     return data["data"]   # {authorization_url, access_code, reference}

    # app/services/payments/paystack.py — additions to PaystackService

    def _is_test_mode(self) -> bool:
        return self._secret.startswith("sk_test_")

    def initialize_transaction(
        self,
        email: str,
        amount: Decimal,
        reference: str,
        callback_url: Optional[str] = None,
        metadata: Optional[dict] = None,
        plan_code: Optional[str] = None,
        subaccount_code: Optional[str] = None,
        channels: Optional[list] = None,
    ) -> dict:
        payload: Dict[str, Any] = {
            "email": email,
            "amount": to_kobo(amount),
            "reference": reference,
            "currency": "NGN",
            "callback_url": callback_url or self._callback_url,
        }
        if metadata:
            payload["metadata"] = metadata
        if plan_code:
            payload["plan"] = plan_code
        if channels:
            payload["channels"] = channels

        if subaccount_code:
            if self._is_test_mode():
                logger.warning(
                    "Ignoring subaccount_code=%s for reference %s — running with a Paystack "
                    "TEST secret key, but subaccounts are mode-specific and this code was very "
                    "likely created under a LIVE key. Sending it would fail with 'Invalid Subaccount.'",
                    subaccount_code, reference,
                )
            else:
                payload["subaccount"] = subaccount_code
                payload["bearer_type"] = "account"

        data = self._post("/transaction/initialize", payload)
        return data["data"]

    def verify_transaction(self, reference: str) -> dict:
        data = self._get(f"/transaction/verify/{reference}")
        return data["data"]

    def list_transactions(self, page: int = 1, per_page: int = 50, customer: Optional[str] = None) -> dict:
        params: Dict[str, Any] = {"page": page, "perPage": per_page}
        if customer:
            params["customer"] = customer
        return self._get("/transaction", params)

    # ── Subscription ──────────────────────────────────────────────────────────

    def create_subscription(self, customer_email: str, plan_code: str, authorization_code: str) -> dict:
        """Create a recurring subscription after successful first payment."""
        payload = {
            "customer": customer_email,
            "plan": plan_code,
            "authorization": authorization_code,
        }
        data = self._post("/subscription", payload)
        return data["data"]

    def get_subscription(self, subscription_code: str) -> dict:
        data = self._get(f"/subscription/{subscription_code}")
        return data["data"]

    def list_subscriptions(self, page: int = 1, per_page: int = 50, customer: Optional[str] = None) -> dict:
        params: Dict[str, Any] = {"page": page, "perPage": per_page}
        if customer:
            params["customer"] = customer
        return self._get("/subscription", params)

    def disable_subscription(self, subscription_code: str, email_token: str) -> dict:
        """Pause / cancel a Paystack subscription."""
        payload = {"code": subscription_code, "token": email_token}
        return self._post("/subscription/disable", payload)

    def enable_subscription(self, subscription_code: str, email_token: str) -> dict:
        """Resume a paused Paystack subscription."""
        payload = {"code": subscription_code, "token": email_token}
        return self._post("/subscription/enable", payload)

    def get_subscription_manage_link(self, subscription_code: str) -> Optional[str]:
        """Return the Paystack-hosted customer management URL."""
        try:
            data = self._get(f"/subscription/{subscription_code}/manage/link")
            return data.get("data", {}).get("link")
        except PaystackError:
            return None

    # ── Plan (Paystack Plan) ──────────────────────────────────────────────────

    def create_plan(self, name: str, interval: str, amount: Decimal, description: str = "") -> dict:
        payload = {
            "name": name,
            "interval": interval,        # daily / weekly / monthly / quarterly / annually
            "amount": to_kobo(amount),
            "currency": "NGN",
            "description": description,
        }
        data = self._post("/plan", payload)
        return data["data"]   # {plan_code, id, ...}

    def update_plan(self, plan_code: str, **kwargs) -> dict:
        payload = {k: v for k, v in kwargs.items() if v is not None}
        return self._put(f"/plan/{plan_code}", payload)

    # app/services/payments/paystack.py
    # def update_plan(
    #     self, plan_code: str, name: Optional[str] = None, 
    #     amount: Optional[Decimal] = None, 
    #     interval: Optional[str] = None) -> dict:
    #     payload = {}
    #     if name: payload["name"] = name
    #     if amount is not None: payload["amount"] = to_kobo(amount)
    #     if interval: payload["interval"] = interval
    #     return self._put(f"/plan/{plan_code}", payload)

    def get_plan(self, plan_code: str) -> dict:
        data = self._get(f"/plan/{plan_code}")
        return data["data"]

    # ── Customer ──────────────────────────────────────────────────────────────

    def get_or_create_customer(self, email: str, name: str, phone: Optional[str] = None) -> dict:
        payload: Dict[str, Any] = {"email": email, "first_name": name.split()[0] if name else ""}
        if len(name.split()) > 1:
            payload["last_name"] = " ".join(name.split()[1:])
        if phone:
            payload["phone"] = phone
        data = self._post("/customer", payload)
        return data["data"]

    # ── Subaccounts (split payments) ──────────────────────────────────────

    def create_subaccount(self, business_name: str, bank_code: str, account_number: str, percentage_charge: float) -> dict:
        """percentage_charge = the TENANT's share (e.g. 98.5 means tenant
        keeps 98.5%, platform_fee_percent implicitly = 100 - this)."""
        payload = {
            "business_name": business_name,
            "bank_code": bank_code,
            "account_number": account_number,
            "percentage_charge": percentage_charge,
        }
        data = self._post("/subaccount", payload)
        return data["data"]

    def update_subaccount(self, subaccount_code: str, **kwargs) -> dict:
        payload = {k: v for k, v in kwargs.items() if v is not None}
        return self._put(f"/subaccount/{subaccount_code}", payload)

    def resolve_account_number(self, account_number: str, bank_code: str) -> dict:
        data = self._get("/bank/resolve", {"account_number": account_number, "bank_code": bank_code})
        return data["data"]

    def list_banks(self) -> list:
        data = self._get("/bank", {"country": "nigeria", "currency": "NGN"})
        return data["data"]
    
    # ── Refund ────────────────────────────────────────────────────────────────

    def refund_transaction(self, transaction_ref: str, amount: Optional[Decimal] = None) -> dict:
        payload: Dict[str, Any] = {"transaction": transaction_ref}
        if amount:
            payload["amount"] = to_kobo(amount)
        data = self._post("/refund", payload)
        return data["data"]

    # ── Webhook verification ──────────────────────────────────────────────────

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        cfg = get_app_config().payments_config.paystack
        secret = cfg.webhook_secret or self._secret
        expected = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected, signature)


# Singleton
_paystack: Optional[PaystackService] = None


def get_paystack() -> PaystackService:
    global _paystack
    if _paystack is None:
        _paystack = PaystackService()
    return _paystack

