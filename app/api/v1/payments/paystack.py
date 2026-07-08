# """app/api/v1/payments.py — Direct order payments, invoices, Paystack webhook."""
# import hashlib
# import hmac
# import json
# import logging
# from datetime import datetime, timezone
# from typing import Optional

# from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request
# from app.models.organization import Organization
# from app.models.payments.providers import TenantProviderAccount
# from app.services.payments import get_provider
# from sqlalchemy import desc
# from sqlalchemy.orm import Session

# from app.api.deps.auth import get_current_user, require_staff_or_admin
# from app.core.config import get_app_config
# from app.core.exceptions.custom_exceptions import CustomAPIException, NotFoundError
# from app.db.database import get_db
# from app.enums.stitch import (
#     PaymentProvider, PaymentPurpose, PaymentStatus
#     )
# from app.enums.billing import  SubscriptionStatus

# from app.models.orders import Order
# from app.models.payments.base import Payment, PaystackWebhookEvent
# # from app.models.subscriptions import Subscription, Plan
# from app.models.tenant_billing import ServicePlan, CustomerSubscription
# from app.models.users import User
# from app.schemas.payments import PaymentInitRequest, PaymentOut, InvoiceCreateRequest
# from app.services.notification_service import notify_payment_confirmed
# from app.services.payments.paystack import PaystackError, get_paystack
# from app.utils.helpers import from_kobo, generate_reference, next_renewal_date
# from app.utils.responses import api_response

# logger = logging.getLogger(__name__)
# router = APIRouter(tags=["Payments"])


# # ─── Initialize ──────────────────────────────────────────────────────────────

# @router.post("/initialize")
# def initialize_payment(
#     payload: PaymentInitRequest,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     ref = payload.reference or generate_reference("ST-PAY")
#     email = payload.email or user.email
#     try:
        
#         # payments.py — initialize_payment, additions
#         org_provider_account = db.query(TenantProviderAccount).filter(
#             TenantProviderAccount.organization_id == user.organization_id,
#             TenantProviderAccount.provider == (db.get(Organization, user.organization_id).preferred_provider),
#             TenantProviderAccount.is_active == True,
#         ).first()

#         provider_client = get_provider(
#             db.get(Organization, user.organization_id).preferred_provider if org_provider_account else "paystack"
#         )

#         ps = provider_client.initialize_transaction(
#             email=email, amount=payload.amount, 
#             reference=ref,
#             callback_url=payload.callback_url,
#             # metadata={...},
#             subaccount_code=org_provider_account.subaccount_code if org_provider_account else None,
#             metadata={
#                 **(payload.metadata or {}),
#                 "user_id": str(user.id),
#                 "purpose": payload.purpose.value,
#             },
#         )
        
#         # ps = get_paystack().initialize_transaction(
#         #     email=email,
#         #     amount=payload.amount,
#         #     reference=ref,
#         #     callback_url=payload.callback_url,
#         #     metadata={
#         #         **(payload.metadata or {}),
#         #         "user_id": str(user.id),
#         #         "purpose": payload.purpose.value,
#         #     },
#         # )
        
#         payment = Payment(
#             user_id=str(user.id),
#             order_id=str(payload.order_id) if payload.order_id else None,
#             customer_subscription_id=str(payload.subscription_id) if payload.subscription_id else None,
#             reference=ref,
#             provider=PaymentProvider.PAYSTACK,
#             purpose=payload.purpose,
#             status=PaymentStatus.PENDING,
#             amount=payload.amount,
#             authorization_url=ps.get("authorization_url"),
#             access_code=ps.get("access_code"),
#             metadata_json=payload.metadata,
#         )
#         db.add(payment)
#         return api_response(
#             success=True,
#             message="Payment initialized.",
#             data={
#                 "reference": ref,
#                 "authorization_url": ps.get("authorization_url"),
#                 "access_code": ps.get("access_code"),
#             },
#         )
#     except PaystackError as exc:
#         raise CustomAPIException(f"Paystack error: {exc.message}", 502, "PAYSTACK_ERROR")


# # ─── Verify ───────────────────────────────────────────────────────────────────

# @router.get("/verify/{reference}")
# def verify_payment(
#     reference: str,
#     background: BackgroundTasks,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     payment = db.query(Payment).filter(Payment.reference == reference).first()
#     if not payment:
#         raise NotFoundError("Payment", reference)
#     if payment.status == PaymentStatus.SUCCESS:
#         return api_response(
#             success=True,
#             message="Payment already verified.",
#             data=PaymentOut.model_validate(payment),
#         )
#     try:
#         tx = get_paystack().verify_transaction(reference)
#     except PaystackError as exc:
#         raise CustomAPIException(f"Verification failed: {exc.message}", 402)

#     if tx.get("status") != "success":
#         payment.status = PaymentStatus.FAILED
#         raise CustomAPIException("Payment not successful.", 402, "PAYMENT_FAILED")

#     payment.status      = PaymentStatus.SUCCESS
#     payment.amount_paid = from_kobo(tx.get("amount", 0))
#     payment.channel     = tx.get("channel")
#     payment.paid_at     = datetime.now(timezone.utc)
#     payment.paystack_id = str(tx.get("id", ""))
#     if auth := tx.get("authorization"):
#         payment.card_type = auth.get("card_type")
#         payment.bank      = auth.get("bank")
#         payment.last4     = auth.get("last4")

#     # Mark order as paid if applicable
#     if payment.order_id:
#         order = db.get(Order, payment.order_id)
#         if order:
#             order.payment_status    = "paid"
#             order.payment_reference = reference

#     amount_str = f"₦{payment.amount_paid:,.0f}" if payment.amount_paid else f"₦{payment.amount:,.0f}"
#     background.add_task(notify_payment_confirmed, db, user.id, amount_str, payment.purpose.value)
#     return api_response(
#         success=True,
#         message="Payment verified.",
#         data=PaymentOut.model_validate(payment),
#     )


# # ─── List payments ────────────────────────────────────────────────────────────

# @router.get("")
# def list_payments(
#     page: int = Query(1, ge=1),
#     page_size: int = Query(20, ge=1, le=100),
#     status: Optional[PaymentStatus] = None,
#     purpose: Optional[PaymentPurpose] = None,
#     admin: User = Depends(require_staff_or_admin),
#     db: Session = Depends(get_db),
# ):
#     q = db.query(Payment)
#     if status:
#         q = q.filter(Payment.status == status)
#     if purpose:
#         q = q.filter(Payment.purpose == purpose)
#     total = q.count()
#     items = q.order_by(desc(Payment.created_at)).offset((page-1)*page_size).limit(page_size).all()
#     return api_response(
#         success=True,
#         message="Payments fetched.",
#         data={
#             "items": [PaymentOut.model_validate(p) for p in items],
#             "page": page,
#             "page_size": page_size,
#             "total": total,
#         },
#     )


# # ─── Invoice ──────────────────────────────────────────────────────────────────

# @router.post("/invoices", status_code=201)
# def create_invoice(
#     payload: InvoiceCreateRequest,
#     staff: User = Depends(require_staff_or_admin),
#     db: Session = Depends(get_db),
# ):
#     ref = generate_reference("ST-INV")
#     payment = Payment(
#         user_id=str(staff.id),
#         order_id=str(payload.order_id) if payload.order_id else None,
#         reference=ref,
#         provider=PaymentProvider.MANUAL,
#         purpose=PaymentPurpose.INVOICE,
#         status=PaymentStatus.PENDING,
#         amount=payload.amount,
#         metadata_json={"customer_name": payload.customer_name, "notes": payload.notes},
#     )
#     db.add(payment)
#     db.flush()
#     return api_response(
#         success=True,
#         message="Invoice created.",
#         data={
#             "id": str(payment.id),
#             "reference": ref,
#             "amount": float(payment.amount),
#             "customer_name": payload.customer_name,
#             "status": payment.status.value,
#             "date": payment.created_at.date().isoformat(),
#         },
#         status_code=201,
#     )


# # ─── Paystack Webhook ─────────────────────────────────────────────────────────

# @router.post("/webhooks/paystack")
# async def paystack_webhook(
#     request: Request,
#     background: BackgroundTasks,
#     x_paystack_signature: Optional[str] = Header(None),
#     db: Session = Depends(get_db),
# ):
#     body = await request.body()

#     # Verify signature
#     cfg = get_app_config().payments_config.paystack
#     secret = cfg.webhook_secret or cfg.secret_key or ""
#     if x_paystack_signature and secret:
#         expected = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
#         if not hmac.compare_digest(expected, x_paystack_signature):
#             raise CustomAPIException("Invalid webhook signature.", 401, "INVALID_SIGNATURE")

#     try:
#         event_data = json.loads(body)
#     except json.JSONDecodeError:
#         raise CustomAPIException("Invalid JSON payload.", 400)

#     event_type = event_data.get("event", "unknown")
#     event_ref  = event_data.get("data", {}).get("reference")
#     event_id   = event_data.get("data", {}).get("id", f"{event_type}-{event_ref}")

#     # Idempotency check
#     existing = db.query(PaystackWebhookEvent).filter(
#         PaystackWebhookEvent.event_id == str(event_id)
#     ).first()
#     if existing and existing.processed:
#         logger.info("Webhook already processed: %s", event_id)
#         return api_response(
#             success=True,
#             message="already processed",
#             data={"status": "ok"},
#         )

#     webhook_event = existing or PaystackWebhookEvent(
#         event_id=str(event_id),
#         event_type=event_type,
#         reference=event_ref,
#         payload=event_data,
#     )
#     if not existing:
#         db.add(webhook_event)
#     db.flush()

#     # Process in background to return 200 fast
#     background.add_task(_process_webhook, str(webhook_event.id), event_data, event_type)
#     return api_response(
#         success=True,
#         message="Webhook received.",
#         data={"status": "ok"},
#     )


# def _process_webhook(webhook_record_id: str, event_data: dict, event_type: str):
#     """Background task — process Paystack webhook event."""
#     from app.db.database import get_session_maker
#     db = get_session_maker()()
#     try:
#         record = db.query(PaystackWebhookEvent).filter(
#             PaystackWebhookEvent.id == webhook_record_id
#         ).first()
#         if not record:
#             return

#         data = event_data.get("data", {})

#         if event_type == "charge.success":
#             _handle_charge_success(data, db)
#         elif event_type in ("subscription.create", "subscription.activate"):
#             _handle_subscription_create(data, db)
#         elif event_type == "subscription.disable":
#             _handle_subscription_disable(data, db)
#         elif event_type == "invoice.payment_failed":
#             _handle_invoice_failed(data, db)
#         elif event_type == "refund.processed":
#             _handle_refund(data, db)

#         record.processed    = True
#         record.processed_at = datetime.now(timezone.utc)
#         db.commit()
#     except Exception as exc:
#         db.rollback()
#         record = db.query(PaystackWebhookEvent).filter(
#             PaystackWebhookEvent.id == webhook_record_id
#         ).first()
#         if record:
#             record.error = str(exc)
#             db.commit()
#         logger.error("Webhook processing error: %s", exc, exc_info=True)
#     finally:
#         db.close()


# def _handle_charge_success(data: dict, db: Session):
#     ref = data.get("reference")
#     if not ref:
#         return
#     payment = db.query(Payment).filter(Payment.reference == ref).first()
#     if not payment or payment.status == PaymentStatus.SUCCESS:
#         return
#     payment.status      = PaymentStatus.SUCCESS
#     payment.amount_paid = from_kobo(data.get("amount", 0))
#     payment.channel     = data.get("channel")
#     payment.paid_at     = datetime.now(timezone.utc)
#     payment.paystack_id = str(data.get("id", ""))
#     if auth := data.get("authorization"):
#         payment.card_type = auth.get("card_type")
#         payment.bank      = auth.get("bank")
#         payment.last4     = auth.get("last4")
#     if payment.order_id:
#         order = db.get(Order, payment.order_id)
#         if order:
#             order.payment_status    = "paid"
#             order.payment_reference = ref


# def _handle_subscription_create(data: dict, db: Session):
#     """Paystack confirms new recurring subscription — update our record."""
#     ps_code  = data.get("subscription_code")
#     email_tok = data.get("email_token")
#     plan_code = data.get("plan", {}).get("plan_code") if isinstance(data.get("plan"), dict) else None
#     if not ps_code:
#         return
#     sub = db.query(CustomerSubscription).filter(
#         CustomerSubscription.paystack_subscription_code == ps_code
#     ).first()
#     if not sub and plan_code:
#         plan = db.query(ServicePlan).filter(ServicePlan.paystack_plan_code == plan_code).first()
#         if plan:
#             sub = db.query(CustomerSubscription).filter(
#                 CustomerSubscription.plan_id == plan.id,
#                 CustomerSubscription.status == SubscriptionStatus.ACTIVE,
#             ).order_by(desc(CustomerSubscription.created_at)).first()
#     if sub:
#         sub.paystack_subscription_code = ps_code
#         sub.paystack_email_token       = email_tok
#         sub.status = SubscriptionStatus.ACTIVE


# def _handle_subscription_disable(data: dict, db: Session):
#     ps_code = data.get("subscription_code")
#     if not ps_code:
#         return
#     sub = db.query(CustomerSubscription).filter(
#         CustomerSubscription.paystack_subscription_code == ps_code
#     ).first()
#     if sub:
#         sub.status = SubscriptionStatus.CANCELED
#         sub.cancelled_at = datetime.now(timezone.utc)


# def _handle_invoice_failed(data: dict, db: Session):
#     ps_code = data.get("subscription", {}).get("subscription_code") if isinstance(data.get("subscription"), dict) else None
#     if not ps_code:
#         return
#     sub = db.query(CustomerSubscription).filter(
#         CustomerSubscription.paystack_subscription_code == ps_code
#     ).first()
#     if sub:
#         logger.warning("Customer Subscription invoice payment failed for sub_id=%d", sub.id)


# def _handle_refund(data: dict, db: Session):
#     ref = data.get("transaction_reference")
#     if not ref:
#         return
#     payment = db.query(Payment).filter(Payment.reference == ref).first()
#     if payment:
#         payment.status = PaymentStatus.REFUNDED








# v2
"""app/api/v1/paystack.py — Direct order payments, invoices, Paystack webhook."""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user, require_staff_or_admin
from app.core.config import get_app_config
from app.core.exceptions.custom_exceptions import CustomAPIException, NotFoundError
from app.db.database import get_db
from app.enums.stitch import PaymentPurpose, PaymentStatus
from app.enums.billing import SubscriptionStatus

from app.models.orders import Order
from app.models.payments.base import Payment, PaystackWebhookEvent
from app.models.tenant_billing import ServicePlan, CustomerSubscription
from app.models.users import User
from app.schemas.payments import PaymentInitRequest, PaymentOut, InvoiceCreateRequest
from app.services.notification_service import notify_payment_confirmed
from app.services.payments.paystack import PaystackError, get_paystack
from app.services.payments import get_provider, PaymentProviderError
from app.services.payments.provider_resolver import _get_provider_for_org
from app.utils.helpers import from_kobo, generate_reference, next_renewal_date
from app.utils.responses import api_response

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Payments"])


# ─── Initialize ──────────────────────────────────────────────────────────────

@router.post("/initialize")
def initialize_payment(
    payload: PaymentInitRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ref = payload.reference or generate_reference("ST-PAY")
    email = payload.email or user.email

    resolved = _get_provider_for_org(db, user.organization_id)

    try:
        ps = resolved.client.initialize_transaction(
            email=email,
            amount=payload.amount,
            reference=ref,
            callback_url=payload.callback_url,
            metadata={
                **(payload.metadata or {}),
                "user_id": str(user.id),
                "purpose": payload.purpose.value,
                "provider": resolved.provider_name,
            },
            subaccount_code=resolved.subaccount_code,
        )
    except PaymentProviderError as exc:
        raise CustomAPIException(f"Payment provider error: {exc.message}", 502, "PAYMENT_PROVIDER_ERROR")

    payment = Payment(
        user_id=str(user.id),
        order_id=str(payload.order_id) if payload.order_id else None,
        customer_subscription_id=str(payload.subscription_id) if payload.subscription_id else None,
        reference=ref,
        provider=resolved.provider_name,
        purpose=payload.purpose,
        status=PaymentStatus.PENDING,
        amount=payload.amount,
        authorization_url=ps.get("authorization_url"),
        access_code=ps.get("access_code"),
        metadata_json=payload.metadata,
    )
    db.add(payment)
    return api_response(
        success=True,
        message="Payment initialized.",
        data={
            "reference": ref,
            "authorization_url": ps.get("authorization_url"),
            "access_code": ps.get("access_code"),
            "provider": resolved.provider_name,
        },
    )


# ─── Verify ───────────────────────────────────────────────────────────────────

@router.get("/verify/{reference}")
def verify_payment(
    reference: str,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payment = db.query(Payment).filter(Payment.reference == reference).first()
    if not payment:
        raise NotFoundError("Payment", reference)
    if payment.status == PaymentStatus.SUCCESS:
        return api_response(
            success=True,
            message="Payment already verified.",
            data=PaymentOut.model_validate(payment),
        )

    # Verify against whichever provider actually processed this payment —
    # not necessarily the org's *current* preferred provider, since that
    # could have changed since the payment was initialized.
    provider_client = get_provider(payment.provider)

    try:
        tx = provider_client.verify_transaction(reference)
    except PaymentProviderError as exc:
        raise CustomAPIException(f"Verification failed: {exc.message}", 402)

    if tx.get("status") != "success":
        payment.status = PaymentStatus.FAILED
        raise CustomAPIException("Payment not successful.", 402, "PAYMENT_FAILED")

    payment.status      = PaymentStatus.SUCCESS
    payment.amount_paid = from_kobo(tx.get("amount", 0))
    payment.channel     = tx.get("channel")
    payment.paid_at     = datetime.now(timezone.utc)
    payment.paystack_id = str(tx.get("id", ""))
    if auth := tx.get("authorization"):
        payment.card_type = auth.get("card_type")
        payment.bank      = auth.get("bank")
        payment.last4     = auth.get("last4")

    if payment.order_id:
        order = db.get(Order, payment.order_id)
        if order:
            order.payment_status    = "paid"
            order.payment_reference = reference

    amount_str = f"₦{payment.amount_paid:,.0f}" if payment.amount_paid else f"₦{payment.amount:,.0f}"
    background.add_task(notify_payment_confirmed, db, user.id, amount_str, payment.purpose.value)
    return api_response(
        success=True,
        message="Payment verified.",
        data=PaymentOut.model_validate(payment),
    )


# ─── List payments ────────────────────────────────────────────────────────────

@router.get("")
def list_payments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[PaymentStatus] = None,
    purpose: Optional[PaymentPurpose] = None,
    admin: User = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
):
    q = db.query(Payment)
    if status:
        q = q.filter(Payment.status == status)
    if purpose:
        q = q.filter(Payment.purpose == purpose)
    total = q.count()
    items = q.order_by(desc(Payment.created_at)).offset((page-1)*page_size).limit(page_size).all()
    return api_response(
        success=True,
        message="Payments fetched.",
        data={
            "items": [PaymentOut.model_validate(p) for p in items],
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


# ─── Invoice ──────────────────────────────────────────────────────────────────

@router.post("/invoices", status_code=201)
def create_invoice(
    payload: InvoiceCreateRequest,
    staff: User = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
):
    ref = generate_reference("ST-INV")
    payment = Payment(
        user_id=str(staff.id),
        order_id=str(payload.order_id) if payload.order_id else None,
        reference=ref,
        provider="manual",
        purpose=PaymentPurpose.INVOICE,
        status=PaymentStatus.PENDING,
        amount=payload.amount,
        metadata_json={"customer_name": payload.customer_name, "notes": payload.notes},
    )
    db.add(payment)
    db.flush()
    return api_response(
        success=True,
        message="Invoice created.",
        data={
            "id": str(payment.id),
            "reference": ref,
            "amount": float(payment.amount),
            "customer_name": payload.customer_name,
            "status": payment.status.value,
            "date": payment.created_at.date().isoformat(),
        },
        status_code=201,
    )


# ─── Paystack Webhook ─────────────────────────────────────────────────────────
# Note: this webhook handler is Paystack-specific (signature scheme, event
# names, and payload shape are all Paystack's). Once OPay/others are live,
# they'll need their OWN webhook endpoint here (e.g. /webhooks/opay) since
# each provider has a different signature verification method and event
# vocabulary — they cannot share this handler as-is.

@router.post("/webhooks/paystack")
async def paystack_webhook(
    request: Request,
    background: BackgroundTasks,
    x_paystack_signature: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    body = await request.body()

    cfg = get_app_config().payments_config.paystack
    secret = cfg.webhook_secret or cfg.secret_key or ""
    if x_paystack_signature and secret:
        expected = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
        if not hmac.compare_digest(expected, x_paystack_signature):
            raise CustomAPIException("Invalid webhook signature.", 401, "INVALID_SIGNATURE")

    try:
        event_data = json.loads(body)
    except json.JSONDecodeError:
        raise CustomAPIException("Invalid JSON payload.", 400)

    event_type = event_data.get("event", "unknown")
    event_ref  = event_data.get("data", {}).get("reference")
    event_id   = event_data.get("data", {}).get("id", f"{event_type}-{event_ref}")

    existing = db.query(PaystackWebhookEvent).filter(
        PaystackWebhookEvent.event_id == str(event_id)
    ).first()
    if existing and existing.processed:
        logger.info("Webhook already processed: %s", event_id)
        return api_response(success=True, message="already processed", data={"status": "ok"})

    webhook_event = existing or PaystackWebhookEvent(
        event_id=str(event_id), event_type=event_type, reference=event_ref, payload=event_data,
    )
    if not existing:
        db.add(webhook_event)
    db.flush()

    background.add_task(_process_webhook, str(webhook_event.id), event_data, event_type)
    return api_response(success=True, message="Webhook received.", data={"status": "ok"})


def _process_webhook(webhook_record_id: str, event_data: dict, event_type: str):
    from app.db.database import get_session_maker
    db = get_session_maker()()
    try:
        record = db.query(PaystackWebhookEvent).filter(
            PaystackWebhookEvent.id == webhook_record_id
        ).first()
        if not record:
            return

        data = event_data.get("data", {})

        if event_type == "charge.success":
            _handle_charge_success(data, db)
        elif event_type in ("subscription.create", "subscription.activate"):
            _handle_subscription_create(data, db)
        elif event_type == "subscription.disable":
            _handle_subscription_disable(data, db)
        elif event_type == "invoice.payment_failed":
            _handle_invoice_failed(data, db)
        elif event_type == "refund.processed":
            _handle_refund(data, db)

        record.processed    = True
        record.processed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        record = db.query(PaystackWebhookEvent).filter(
            PaystackWebhookEvent.id == webhook_record_id
        ).first()
        if record:
            record.error = str(exc)
            db.commit()
        logger.error("Webhook processing error: %s", exc, exc_info=True)
    finally:
        db.close()


def _handle_charge_success(data: dict, db: Session):
    ref = data.get("reference")
    if not ref:
        return
    payment = db.query(Payment).filter(Payment.reference == ref).first()
    if not payment or payment.status == PaymentStatus.SUCCESS:
        return
    payment.status      = PaymentStatus.SUCCESS
    payment.amount_paid = from_kobo(data.get("amount", 0))
    payment.channel     = data.get("channel")
    payment.paid_at     = datetime.now(timezone.utc)
    payment.paystack_id = str(data.get("id", ""))
    if auth := data.get("authorization"):
        payment.card_type = auth.get("card_type")
        payment.bank      = auth.get("bank")
        payment.last4     = auth.get("last4")
    if payment.order_id:
        order = db.get(Order, payment.order_id)
        if order:
            order.payment_status    = "paid"
            order.payment_reference = ref


def _handle_subscription_create(data: dict, db: Session):
    ps_code   = data.get("subscription_code")
    email_tok = data.get("email_token")
    plan_code = data.get("plan", {}).get("plan_code") if isinstance(data.get("plan"), dict) else None
    if not ps_code:
        return
    sub = db.query(CustomerSubscription).filter(
        CustomerSubscription.paystack_subscription_code == ps_code
    ).first()
    if not sub and plan_code:
        plan = db.query(ServicePlan).filter(ServicePlan.paystack_plan_code == plan_code).first()
        if plan:
            sub = db.query(CustomerSubscription).filter(
                CustomerSubscription.plan_id == plan.id,
                CustomerSubscription.status == SubscriptionStatus.ACTIVE,
            ).order_by(desc(CustomerSubscription.created_at)).first()
    if sub:
        sub.paystack_subscription_code = ps_code
        sub.paystack_email_token       = email_tok
        sub.status = SubscriptionStatus.ACTIVE


def _handle_subscription_disable(data: dict, db: Session):
    ps_code = data.get("subscription_code")
    if not ps_code:
        return
    sub = db.query(CustomerSubscription).filter(
        CustomerSubscription.paystack_subscription_code == ps_code
    ).first()
    if sub:
        sub.status = SubscriptionStatus.CANCELED  # fixed: was CANCELED (one L) — matches enum def
        sub.cancelled_at = datetime.now(timezone.utc)


def _handle_invoice_failed(data: dict, db: Session):
    ps_code = data.get("subscription", {}).get("subscription_code") if isinstance(data.get("subscription"), dict) else None
    if not ps_code:
        return
    sub = db.query(CustomerSubscription).filter(
        CustomerSubscription.paystack_subscription_code == ps_code
    ).first()
    if sub:
        logger.warning("Customer Subscription invoice payment failed for sub_id=%s", sub.id)


def _handle_refund(data: dict, db: Session):
    ref = data.get("transaction_reference")
    if not ref:
        return
    payment = db.query(Payment).filter(Payment.reference == ref).first()
    if payment:
        payment.status = PaymentStatus.REFUNDED

