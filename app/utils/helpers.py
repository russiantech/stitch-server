# app/utils/helpers.py
"""
app/utils/helpers.py — Shared utility functions for Stitch.
"""
import hashlib
import hmac
import random
import re
import string
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from fastapi import Request
from slugify import slugify as _slugify

def make_slug(text: str, suffix: bool = False) -> str:
    base = _slugify(text)
    if suffix:
        return f"{base}-{uuid.uuid4().hex[:6]}"
    return base


def generate_reference(prefix: str = "ST") -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rnd = uuid.uuid4().hex[:6].upper()
    return f"{prefix}-{ts}-{rnd}"


def generate_order_reference(order_type: str = "LD") -> str:
    ts = datetime.now(timezone.utc).strftime("%y%m%d")
    rnd = random.randint(1000, 9999)
    return f"{order_type.upper()}-{ts}-{rnd}"


def generate_referral_code(name: str) -> str:
    clean = re.sub(r"[^A-Za-z]", "", name).upper()[:6]
    suffix = uuid.uuid4().hex[:4].upper()
    return f"ST-{clean}{suffix}"


def generate_otp(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def next_renewal_date(interval: str, from_date: Optional[date] = None) -> date:
    base = from_date or datetime.now(timezone.utc).date()
    mapping = {
        "daily":     timedelta(days=1),
        "weekly":    timedelta(weeks=1),
        "monthly":   timedelta(days=30),
        "quarterly": timedelta(days=91),
        "annually":  timedelta(days=365),
    }
    delta = mapping.get(interval, timedelta(days=30))
    return base + delta


def apply_priority_surcharge(amount: Decimal, priority: str) -> Decimal:
    if priority == "Express":
        return (amount * Decimal("0.5")).quantize(Decimal("0.01"))
    if priority == "Urgent":
        return (amount * Decimal("1.0")).quantize(Decimal("0.01"))
    return Decimal("0.00")


def verify_paystack_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)


def mask_email(email: str) -> str:
    parts = email.split("@")
    if len(parts) != 2:
        return "***"
    local, domain = parts
    visible = local[:2] if len(local) > 2 else local[0]
    return f"{visible}{'*' * (len(local) - len(visible))}@{domain}"


def to_kobo(naira: Decimal) -> int:
    return int(naira * 100)


def from_kobo(kobo: int) -> Decimal:
    return Decimal(kobo) / 100


def is_valid_phone_ng(phone: str) -> bool:
    cleaned = re.sub(r"[\s\-\(\)]", "", phone)
    return bool(re.match(r"^(\+234|0)[789]\d{9}$", cleaned))


def normalize_phone_ng(phone: str) -> str:
    cleaned = re.sub(r"[\s\-\(\)]", "", phone)
    if cleaned.startswith("0"):
        return "+234" + cleaned[1:]
    return cleaned


# more
def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


def generate_code(length: int = 6) -> str:
    chars = string.ascii_uppercase + string.digits
    chars = chars.translate(str.maketrans("", "", "0O1I"))
    return "".join(secrets.choice(chars) for _ in range(length))
