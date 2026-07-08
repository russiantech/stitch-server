# app/schemas/payouts.py
from pydantic import BaseModel, Field
from decimal import Decimal

class BankResolveRequest(BaseModel):
    provider: str = "opay"
    account_number: str
    bank_code: str

class PayoutSetupRequest(BaseModel):
    provider: str = "opay"
    account_number: str
    bank_code: str
    platform_fee_percent: Decimal = Field(default=Decimal("0.00"), ge=0, le=100)

