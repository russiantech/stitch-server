
"""
app/enums/stitch.py — All domain enumerations for the Stitch platform.
Single source of truth — used by models, schemas and business logic.
"""
import enum


# ─── User ────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    ADMIN    = "admin"
    STAFF    = "staff"
    DRIVER   = "driver"
    CUSTOMER = "customer"


class UserStatus(str, enum.Enum):
    ACTIVE    = "active"
    INACTIVE  = "inactive"
    SUSPENDED = "suspended"
    PENDING   = "pending"     # invited but not yet activated


# ─── Order (shared) ──────────────────────────────────────────────────────────

class OrderType(str, enum.Enum):
    LAUNDRY = "laundry"
    FASHION = "fashion"


class OrderPriority(str, enum.Enum):
    NORMAL  = "Normal"
    EXPRESS = "Express"
    URGENT  = "Urgent"


class PaymentMethodType(str, enum.Enum):
    SUBSCRIPTION = "subscription"
    DIRECT       = "direct"
    CASH         = "cash"
    TRANSFER     = "transfer"


# ─── Laundry order workflow ───────────────────────────────────────────────────

class LaundryStatus(str, enum.Enum):
    RECEIVED          = "Received"
    SORTED            = "Sorted"
    WASHING           = "Washing"
    DRYING            = "Drying"
    IRONING           = "Ironing"
    FOLDING           = "Folding"
    PACKING           = "Packing"
    READY_FOR_DELIVERY = "Ready For Delivery"
    OUT_FOR_DELIVERY  = "Out For Delivery"
    DELIVERED         = "Delivered"
    COMPLETED         = "Completed"
    CANCELLED         = "Cancelled"


LAUNDRY_STATUS_FLOW = [
    LaundryStatus.RECEIVED,
    LaundryStatus.SORTED,
    LaundryStatus.WASHING,
    LaundryStatus.DRYING,
    LaundryStatus.IRONING,
    LaundryStatus.FOLDING,
    LaundryStatus.PACKING,
    LaundryStatus.READY_FOR_DELIVERY,
    LaundryStatus.OUT_FOR_DELIVERY,
    LaundryStatus.DELIVERED,
    LaundryStatus.COMPLETED,
]


# ─── Fashion order workflow ───────────────────────────────────────────────────

class FashionStatus(str, enum.Enum):
    CONSULTATION    = "Consultation"
    MEASUREMENT     = "Measurement"
    DESIGN_APPROVAL = "Design Approval"
    PRODUCTION      = "Production"
    FITTING         = "Fitting"
    ADJUSTMENTS     = "Adjustments"
    READY           = "Ready"
    DELIVERY        = "Delivery"
    COMPLETED       = "Completed"
    CANCELLED       = "Cancelled"


FASHION_STATUS_FLOW = [
    FashionStatus.CONSULTATION,
    FashionStatus.MEASUREMENT,
    FashionStatus.DESIGN_APPROVAL,
    FashionStatus.PRODUCTION,
    FashionStatus.FITTING,
    FashionStatus.ADJUSTMENTS,
    FashionStatus.READY,
    FashionStatus.DELIVERY,
    FashionStatus.COMPLETED,
]


class FashionServiceType(str, enum.Enum):
    CUSTOM_TAILORING      = "Custom Tailoring"
    ALTERATION            = "Alteration"
    REPAIR                = "Repair"
    BESPOKE_DESIGN        = "Bespoke Design"
    MATERIAL_PICKUP       = "Material Pickup"
    DESIGN_CONSULTATION   = "Design Consultation"


# ─── Subscription / Plan ─────────────────────────────────────────────────────

class PlanInterval(str, enum.Enum):
    DAILY     = "daily"
    WEEKLY    = "weekly"
    MONTHLY   = "monthly"
    QUARTERLY = "quarterly"
    ANNUALLY  = "annually"


# class SubscriptionStatus(str, enum.Enum):
#     ACTIVE    = "active"
#     PAUSED    = "paused"
#     CANCELLED = "cancelled"
#     EXPIRED   = "expired"
#     PENDING   = "pending"      # initiated payment, not yet confirmed


# ─── Payment ─────────────────────────────────────────────────────────────────

class PaymentStatus(str, enum.Enum):
    PENDING    = "pending"
    SUCCESS    = "success"
    FAILED     = "failed"
    ABANDONED  = "abandoned"
    REFUNDED   = "refunded"
    REVERSED   = "reversed"


class PaymentProvider(str, enum.Enum):
    PAYSTACK        = "paystack"
    OPAY            = "opay"
    PALMPAY         = "palmpay"
    FLUTTERWAVE     = "flutterwave"
    MANUAL          = "manual"
    CASH            = "cash"
    


class PaymentPurpose(str, enum.Enum):
    SUBSCRIPTION = "subscription"
    ORDER        = "order"
    INVOICE      = "invoice"
    TOP_UP       = "top_up"


# ─── Inventory ───────────────────────────────────────────────────────────────

class InventoryCategory(str, enum.Enum):
    DETERGENT        = "Detergent"
    CHEMICAL         = "Chemical"
    PACKAGING        = "Packaging"
    FASHION_MATERIAL = "Fashion Material"
    ACCESSORY        = "Accessory"
    EQUIPMENT        = "Equipment"
    OTHER            = "Other"


class InventoryStatus(str, enum.Enum):
    IN_STOCK   = "In Stock"
    LOW_STOCK  = "Low Stock"
    OUT_OF_STOCK = "Out of Stock"


class InventoryLogAction(str, enum.Enum):
    RESTOCK  = "restock"
    DEDUCT   = "deduct"
    ADJUST   = "adjust"
    DISCARD  = "discard"


# ─── Notification ────────────────────────────────────────────────────────────

class NotificationType(str, enum.Enum):
    ORDER        = "order"
    SUBSCRIPTION = "subscription"
    PAYMENT      = "payment"
    SYSTEM       = "system"
    PROMOTION    = "promotion"
    LOYALTY      = "loyalty"
    DELIVERY     = "delivery"


# ─── Loyalty ─────────────────────────────────────────────────────────────────

class LoyaltyAction(str, enum.Enum):
    EARNED   = "earned"
    REDEEMED = "redeemed"
    ADJUSTED = "adjusted"
    EXPIRED  = "expired"


# ─── Usage ───────────────────────────────────────────────────────────────────

class UsagePaymentSource(str, enum.Enum):
    SUBSCRIPTION = "subscription"
    DIRECT       = "direct"
    CASH         = "cash"

