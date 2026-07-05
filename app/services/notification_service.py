"""app/services/notification_service.py — Create in-app notifications."""
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.notifications import Notification
from app.enums.stitch import NotificationType

logger = logging.getLogger(__name__)


def create_notification(
    db: Session,
    user_id: UUID,
    title: str,
    message: str,
    notif_type: NotificationType = NotificationType.SYSTEM,
    action_url: Optional[str] = None,
    meta: Optional[dict] = None,
) -> Notification:
    notif = Notification(
        user_id=user_id, title=title, message=message,
        type=notif_type, action_url=action_url, meta=meta,
    )
    db.add(notif)
    db.flush()
    return notif


def notify_order_status(db: Session, user_id: UUID, order_ref: str, status: str, order_type: str = "laundry") -> None:
    url = f"/orders"
    messages = {
        "Received":          ("Order received ✅",            f"We've received order {order_ref}. We'll start processing shortly."),
        "Washing":           ("Laundry in progress 🫧",       f"Order {order_ref} is now being washed."),
        "Ready For Delivery":("Ready for pickup 📦",          f"Order {order_ref} is packed and ready. Delivery coming soon!"),
        "Out For Delivery":  ("On the way 🚚",                f"Order {order_ref} is out for delivery."),
        "Delivered":         ("Delivered! 🎉",                f"Order {order_ref} has been delivered."),
        "Completed":         ("Order complete ✨",            f"Order {order_ref} is complete. Thank you for using Stitch!"),
        "Fitting":           ("Fitting scheduled 📐",         f"Order {order_ref}: fitting stage reached."),
        "Ready":             ("Your fashion order is ready 👗", f"Order {order_ref} is ready. Delivery incoming!"),
    }
    title, msg = messages.get(status, (f"Order {order_ref} updated", f"Status: {status}"))
    create_notification(db, user_id, title, msg, NotificationType.ORDER, url, {"order_ref": order_ref, "status": status})


def notify_subscription_activated(db: Session, user_id: UUID, plan_name: str, units: int) -> None:
    create_notification(
        db, user_id,
        f"Subscription active — {plan_name}",
        f"Your {plan_name} subscription is now active. {units} units added to your balance.",
        NotificationType.SUBSCRIPTION, "/subscriptions",
        {"plan_name": plan_name, "units": units},
    )


def notify_subscription_topped_up(db: Session, user_id: UUID, plan_name: str, units: int) -> None:
    create_notification(
        db, user_id,
        f"Subscription topped up 🔄",
        f"Your {plan_name} plan was renewed. {units} fresh units added, billing period reset.",
        NotificationType.SUBSCRIPTION, "/subscriptions",
    )


def notify_low_units(db: Session, user_id: UUID, plan_name: str, remaining: int) -> None:
    create_notification(
        db, user_id,
        "⚠️ Low subscription units",
        f"Your {plan_name} plan has only {remaining} units left. Top up to avoid interruptions.",
        NotificationType.SUBSCRIPTION, "/subscriptions",
    )


def notify_payment_confirmed(db: Session, user_id: UUID, amount_formatted: str, purpose: str) -> None:
    create_notification(
        db, user_id,
        "Payment confirmed ✅",
        f"Payment of {amount_formatted} for {purpose} was successfully processed.",
        NotificationType.PAYMENT, "/payments",
    )

