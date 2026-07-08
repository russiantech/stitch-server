# app/services/payment_providers/__init__.py
from app.services.payments.base import PaymentProviderBase, PaymentProviderError
from app.services.payments.paystack import PaystackService
from app.services.payments.opay import OpayService
from app.services.payments.flutterwave import FlutterWaveService
from app.services.payments.palmpay import PalmPayService

_PROVIDERS = {
    "paystack": PaystackService,
    "opay": OpayService,
    "palmpay": PalmPayService,       # add once needed
    "flutterwave": FlutterWaveService,
}

_instances: dict = {}

def get_provider(name: str) -> PaymentProviderBase:
    name = (name or "opay").lower()
    if name not in _PROVIDERS:
        raise ValueError(f"Unknown payment provider: {name}")
    if name not in _instances:
        _instances[name] = _PROVIDERS[name]()
    return _instances[name]