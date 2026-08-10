# app/schemas/payouts.py
from pydantic import BaseModel, Field
from decimal import Decimal

class BankResolveRequest(BaseModel):
    provider: str = "paystack"
    account_number: str
    bank_code: str

class PayoutSetupRequest(BankResolveRequest):
    platform_fee_percent: Decimal = Field(default=Decimal("0.00"), ge=0, le=100)

