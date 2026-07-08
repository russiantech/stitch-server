# app/services/payments/base.py
"""app/services/payments/base.py — Common interface every payment
provider (Paystack, OPay, PalmPay, Flutterwave) must implement, so call
sites never branch on provider name directly."""
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional


class PaymentProviderError(Exception):
    def __init__(self, message: str, status_code: int = 400, raw: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.raw = raw or {}


class PaymentProviderBase(ABC):
    name: str  # set by subclass, matches PaymentProvider enum value

    @abstractmethod
    def initialize_transaction(
        self, email: str, amount: Decimal, reference: str,
        callback_url: Optional[str] = None, metadata: Optional[dict] = None,
        subaccount_code: Optional[str] = None, channels: Optional[list] = None,
    ) -> dict:
        """Returns {authorization_url, access_code, reference}."""
        ...

    @abstractmethod
    def verify_transaction(self, reference: str) -> dict:
        """Returns provider's raw transaction data (status, amount, channel, ...)."""
        ...

    @abstractmethod
    def create_subaccount(
        self, business_name: str, bank_code: str, account_number: str, percentage_charge: float,
    ) -> dict:
        """Returns {subaccount_code, ...}."""
        ...

    @abstractmethod
    def resolve_account_number(self, account_number: str, bank_code: str) -> dict:
        """Returns {account_name, account_number} — used to verify bank details before saving."""
        ...

    @abstractmethod
    def list_banks(self) -> list:
        """Returns [{name, code}, ...] for populating a bank-select dropdown."""
        ...

    @abstractmethod
    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        ...