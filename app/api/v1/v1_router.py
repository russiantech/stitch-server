"""app/api/v1_router.py — Mounts all v1 sub-routers."""
from fastapi import APIRouter

from app.api.v1 import (
    auth, users, orders, pricing, products, 
    inventory, notifications, analytics, customer_subscriptions, organizations
)
from app.api.v1.payments import (
    paystack, opay, palmpay, flutterwave, payouts
)

v1_router = APIRouter()

v1_router.include_router(auth.router,                   prefix="/auth",       tags=["Auth"])
v1_router.include_router(organizations.router,          prefix="/organizations", tags=["Organizations"])
v1_router.include_router(users.router,                  prefix="/users",      tags=["Users"])
v1_router.include_router(orders.router,                 prefix="/orders",     tags=["Orders"])
v1_router.include_router(customer_subscriptions.router, prefix="/subscriptions", tags=["Subscriptions"])

v1_router.include_router(payouts.router,               prefix="/payouts",   tags=["Payouts"])
v1_router.include_router(paystack.router,               prefix="/payments",   tags=["Payments"])
v1_router.include_router(opay.router,                   prefix="/opay",   tags=["Payments"])
v1_router.include_router(opay.router,                   prefix="/opay",   tags=["Payments"])
v1_router.include_router(palmpay.router,                prefix="/palmpay",   tags=["Payments"])
v1_router.include_router(flutterwave.router,            prefix="/flutterwave",   tags=["Payments"])

v1_router.include_router(pricing.router,                prefix="/pricing",    tags=["Pricing"])
v1_router.include_router(products.router,               prefix="/products",   tags=["Products"])
v1_router.include_router(inventory.router,              prefix="/inventory",  tags=["Inventory"])
v1_router.include_router(notifications.router,          prefix="/notifications", tags=["Notifications"])
v1_router.include_router(analytics.router,              prefix="/analytics",  tags=["Analytics"])

