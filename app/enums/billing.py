from enum import Enum

class BillingModel(str, Enum):
    FREE = "free"
    FLAT_RATE = "flat_rate"
    USAGE_BASED = "usage_based"
    HYBRID = "hybrid"
    PAY_AS_YOU_GO = "pay_as_you_go"

class BillingInterval(str, Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"
    WEEKLY = "weekly"
    QUARTERLY = "quarterly"
    PAY_AS_YOU_GO = "pay_as_you_go"

class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    PARTIAL = "partial"
    OVERDUE = "overdue"
    CANCELED = "canceled"
    DISPUTED = "disputed"

class AddOnCategory(str, Enum):
    AI = "ai"
    MESSAGING = "messaging"
    BRANDING = "branding"
    DELIVERY = "delivery"
    MARKETING = "marketing"
    INTEGRATION = "integration"
    ANALYTICS = "analytics"

class MetricCategory(str, Enum):
    ORDERS = "orders"
    MESSAGING = "messaging"
    STORAGE = "storage"
    COMPUTING = "computing"
    STAFF = "staff"

class AddOnBillingModel(str, Enum):
    FLAT = "flat"
    PER_USER = "per_user"
    PER_ORDER = "per_order"
    PER_SMS = "per_sms"

# Extend existing PaymentPurpose
class PaymentPurpose(str, Enum):
    ORDER = "order"
    PLATFORM_SUBSCRIPTION = "platform_subscription"
    ADD_ON = "add_on"
    USAGE_OVERAGE = "usage_overage"
    TRANSACTION_FEE = "transaction_fee"
    SERVICE_SUBSCRIPTION = "service_subscription"
    WALLET_TOPUP = "wallet_topup"
    REFUND = "refund"

# Extend existing SubscriptionStatus
class SubscriptionStatus(str, Enum):
    PENDING = "pending"
    TRIALING = "trialing"
    ACTIVE = "active"
    PAUSED = "paused"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    EXPIRED = "expired"
    SUSPENDED = "suspended"   # non-payment / ToS violation

