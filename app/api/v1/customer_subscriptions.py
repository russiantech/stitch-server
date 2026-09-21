"""
app/api/v1/customer_subscriptions.py — Plans, Subscriptions, Paystack recurring, Usage.

Key business rules:
  1. Same plan + user → top_up_reset() (add units, reset billing period)
  2. Different plan → new Subscription row
  3. Multiple different plans active in parallel — all units pool together
  4. Usage can be merged across multiple subscriptions in one request
"""
import logging
from datetime import datetime, timezone
# from operator import or_
from sqlalchemy import desc, or_
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from app.services.payments import get_provider
from app.api.deps.rbac import require_roles
from sqlalchemy.orm import Session, joinedload

from app.api.deps.auth import get_current_user, require_admin, require_staff_or_admin
from app.core.exceptions.custom_exceptions import (
    ConflictError, CustomAPIException, InsufficientUnitsError, NotFoundError,
)
from app.db.database import get_db
from app.enums.stitch import (
    PaymentPurpose, PaymentStatus, 
    PaymentProvider, UsagePaymentSource
)

from app.enums.billing import SubscriptionStatus
from app.models.users import User
# from app.models.subscriptions import Plan, Subscription, UsageLog
from app.models.tenant_billing import ServicePlan, CustomerSubscription, CustomerUsageLog
from app.models.payments.base import Payment
from app.schemas.subscriptions import (
    PlanCreate, PlanOut, PlanUpdate,
    SubscriptionInitiateRequest, SubscriptionOut,
    UsageRecordRequest, CustomerUsageLogOut, CustomerUsageStatsOut,
)
from app.services.email_service import send_subscription_activated
from app.services.notification_service import (
    notify_subscription_activated, notify_subscription_topped_up, notify_low_units,
)
from app.services.payments.paystack import PaystackError, get_paystack

from app.core.config.loader import get_app_config
from app.services.payments.base import PaymentProviderError
from app.services.payments.provider_resolver import _get_provider_for_org, initialize_with_recovery

from app.utils.helpers import from_kobo, generate_reference, next_renewal_date
from app.utils.responses import api_response


logger = logging.getLogger(__name__)
router = APIRouter(tags=["Subscriptions & Plans"])


# ─── PLANS ─────────────────────────────────────────────────────────────────

# @router.get("/plans")
# def list_plans(db: Session = Depends(get_db)):
#     plans = db.query(ServicePlan).filter(ServicePlan.is_active == True).order_by(ServicePlan.display_order).all()
#     return api_response(
#         success=True,
#         message="Plans fetched.",
#         data=[PlanOut.model_validate(p) for p in plans],
#     )


# @router.get("/plans/{plan_id}")
# def get_plan(plan_id: str, db: Session = Depends(get_db)):
#     p = db.get(ServicePlan, plan_id)
#     if not p:
#         raise NotFoundError("Plan", plan_id)
#     return api_response(
#         success=True,
#         message="Plan fetched.",
#         data=PlanOut.model_validate(p),
#     )

# v2
@router.get("/plans")
def list_plans(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Global defaults (organization_id IS NULL) + this org's own custom
    # plans — never another org's custom plans.
    plans = (
        db.query(ServicePlan)
        .filter(
            or_(ServicePlan.organization_id.is_(None), ServicePlan.organization_id == user.organization_id),
            ServicePlan.is_active == True,
        )
        .order_by(ServicePlan.display_order)
        .all()
    )
    return api_response(success=True, message="Plans fetched.", data=[PlanOut.model_validate(p) for p in plans])


@router.get("/plans/{plan_id}")
def get_plan(
    plan_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p = db.query(ServicePlan).filter(
        ServicePlan.id == plan_id,
        or_(ServicePlan.organization_id.is_(None), ServicePlan.organization_id == user.organization_id),
    ).first()
    if not p:
        raise NotFoundError("Plan", plan_id)
    return api_response(success=True, message="Plan fetched.", data=PlanOut.model_validate(p))

@router.post("/plans", status_code=201)
def create_plan(
    payload: PlanCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    existing = db.query(ServicePlan).filter(ServicePlan.name == payload.name).first()
    if existing:
        raise ConflictError(f"Plan '{payload.name}' already exists.")

    # plan = ServicePlan(**payload.model_dump())
    plan = ServicePlan(organization_id=admin.organization_id, **payload.model_dump())
    db.add(plan); db.flush()

    # Optionally create plan on Paystack for recurring billing
    if not plan.paystack_plan_code:
        try:
            ps_plan = get_paystack().create_plan(
                name=plan.name,
                interval=plan.interval.value,
                amount=plan.amount,
                description=plan.description or "",
            )
            plan.paystack_plan_code = ps_plan.get("plan_code")
            plan.paystack_plan_id   = str(ps_plan.get("id", ""))
        except PaystackError as exc:
            logger.warning("Could not create Paystack plan: %s", exc)

    return api_response(
        success=True,
        message="Plan created.",
        data=PlanOut.model_validate(plan),
        status_code=201,
    )


# @router.put("/plans/{plan_id}")
# def update_plan(
#     plan_id: str,
#     payload: PlanUpdate,
#     admin: User = Depends(require_admin),
#     db: Session = Depends(get_db),
# ):
#     plan = db.get(ServicePlan, plan_id)
#     if not plan:
#         raise NotFoundError("Plan", plan_id)
#     for k, v in payload.model_dump(exclude_none=True).items():
#         setattr(plan, k, v)
#     return api_response(
#         success=True,
#         message="Plan updated.",
#         data=PlanOut.model_validate(plan),
#     )

# v2
@router.put("/plans/{plan_id}", dependencies=[Depends(require_roles("admin", "super_admin"))])
def update_plan(
    plan_id: str,
    payload: PlanUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = db.query(ServicePlan).filter(
        ServicePlan.id == plan_id, ServicePlan.organization_id == user.organization_id
    ).first()
    if not plan:
        raise NotFoundError("Plan", plan_id)

    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(plan, k, v)

    # ── Sync to Paystack — this is what's missing ──
    if plan.paystack_plan_code:
        try:
            get_paystack().update_plan(
                plan.paystack_plan_code,
                name=plan.name,
                amount=plan.amount,
                interval=plan.interval.value,
            )
        
        except PaystackError as exc:
            logger.error("Failed to sync plan %s to Paystack: %s", plan.id, exc)
            raise CustomAPIException(
                f"Plan updated locally, but Paystack sync failed: {exc.message}. "
                "Customers may still see old pricing until this is resolved.",
                502, "PAYSTACK_SYNC_FAILED",
            )

    db.commit()
    db.refresh(plan)
    return api_response(True, "Plan updated.", data=PlanOut.model_validate(plan))

@router.delete("/plans/{plan_id}")
def delete_plan(
    plan_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    plan = db.get(ServicePlan, plan_id)
    if not plan:
        raise NotFoundError("Plan", plan_id)
    active_subs = db.query(CustomerSubscription).filter(
        CustomerSubscription.plan_id == plan_id,
        CustomerSubscription.status == SubscriptionStatus.ACTIVE,
    ).count()
    if active_subs:
        raise CustomAPIException(
            f"Cannot delete plan with {active_subs} active subscription(s). Deactivate it instead.",
            409, "HAS_ACTIVE_SUBS",
        )
    plan.is_active = False   # soft deactivate
    return api_response(success=True, message="Plan deactivated.")


# ─── SUBSCRIPTIONS ────────────────────────────────────────────────────────────

@router.get("/my")
def my_subscriptions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    subs = (db.query(CustomerSubscription)
            .options(joinedload(CustomerSubscription.plan))
            .filter(CustomerSubscription.user_id == user.id)
            .order_by(desc(CustomerSubscription.created_at)).all())
    return api_response(
        success=True,
        message="Subscriptions fetched.",
        data=[SubscriptionOut.from_orm_with_plan(s) for s in subs],
    )


@router.get("/user/{user_id}")
def user_subscriptions(
    user_id: str,
    staff: User = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
):
    if not staff.organization_id:
        raise NotFoundError("Organization", "none")
    user = db.query(User).filter(User.id == user_id, User.organization_id == staff.organization_id).first()
    if not user:
        raise NotFoundError("User", user_id)
    
    subs = (
        db.query(CustomerSubscription).options(joinedload(CustomerSubscription.plan))
            .filter(CustomerSubscription.user_id == user_id)
            .order_by(desc(CustomerSubscription.created_at)).all()
        )
    return api_response(
        success=True,
        message="User subscriptions fetched.",
        data=[SubscriptionOut.from_orm_with_plan(s) for s in subs],
    )


@router.get("")
def all_subscriptions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[SubscriptionStatus] = None,
    admin: User = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
):
    q = db.query(CustomerSubscription).options(joinedload(CustomerSubscription.plan), joinedload(CustomerSubscription.user))
    if status:
        q = q.filter(CustomerSubscription.status == status)
    total = q.count()
    subs  = q.order_by(desc(CustomerSubscription.created_at)).offset((page-1)*page_size).limit(page_size).all()
    return api_response(
        success=True,
        message="Subscriptions fetched.",
        data={
            "items": [SubscriptionOut.from_orm_with_plan(s) for s in subs],
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


# @router.post("/payment/{plan_id}/paystack")
# def initiate_subscription(
#     plan_id: str,
#     payload: SubscriptionInitiateRequest,
#     background: BackgroundTasks,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     """
#     Initiate subscription payment via Paystack.
#     - If plan_code exists → Paystack recurring plan (auto-renews)
#     - If user already has this plan → top-up (same endpoint)
#     Returns: { authorization_url, reference } for the frontend to redirect/open popup.
#     """
#     plan = db.get(ServicePlan, plan_id)
#     if not plan or not plan.is_active:
#         raise NotFoundError("Plan", plan_id)

#     email = payload.email or user.email
    
#     ref   = generate_reference("ST-SUB")

#     existing_sub = db.query(CustomerSubscription).options(joinedload(CustomerSubscription.plan)).filter(
#         CustomerSubscription.user_id == user.id,
#         CustomerSubscription.plan_id == plan_id,
#         CustomerSubscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.PAUSED]),
#     ).first()
#     is_topup = existing_sub is not None

#     # Create payment record first
#     payment = Payment(
#         user_id=user.id,
#         customer_subscription_id=existing_sub.id if existing_sub else None,
#         reference=ref,
#         provider=PaymentProvider.PAYSTACK,
#         purpose=PaymentPurpose.TOP_UP if is_topup else PaymentPurpose.SUBSCRIPTION,
#         status=PaymentStatus.PENDING,
#         amount=plan.amount,
#         metadata_json={
#             "plan_id": str(plan.id), 
#             "plan_name": plan.name,
#             "is_topup": is_topup, 
#             "user_id": str(user.id),
#         },
#     )
#     db.add(payment); db.flush()

#     # Call Paystack — use plan_code for recurring if available
#     try:
#         ps_data = get_paystack().initialize_transaction(
#             email=email,
#             amount=plan.amount,
#             reference=ref,
#             callback_url=payload.callback_url or __import__(
#                 "app.core.config", fromlist=["get_app_config"]
#             ).get_app_config().payments_config.paystack.callback_url,
#             plan_code=plan.paystack_plan_code,   # recurring if set
#             metadata={
#                 "plan_id": str(plan.id), "plan_name": plan.name,
#                 "is_topup": is_topup, "user_id": str(user.id),
#                 "payment_id": str(payment.id),
#             },
#         )
#         payment.paystack_id  = ps_data.get("access_code")
#         payment.access_code  = ps_data.get("access_code")
#         payment.authorization_url = ps_data.get("authorization_url")
#         data={
#                 "reference": ref,
#                 "authorization_url": ps_data.get("authorization_url"),
#                 "access_code": ps_data.get("access_code"),
#                 "is_topup": is_topup,
#                 "plan": PlanOut.model_validate(plan),
#             }
#         logger.info(f"Initiated subscription payment: {data}")
        
#         return api_response(
#             success=True,
#             message="Payment initiated.",
#             data=data
#         )
#     except PaystackError as exc:
#         payment.status = PaymentStatus.FAILED
#         raise CustomAPIException(f"Payment initiation failed: {exc.message}", 502, "PAYSTACK_ERROR")

# v2

# @router.post("/payment/{plan_id}/paystack")
# def initiate_subscription(
#     plan_id: str,
#     payload: SubscriptionInitiateRequest,
#     background: BackgroundTasks,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     """
#     Initiate subscription payment via the org's configured payment
#     provider (default OPay, falls back to Paystack if unconfigured).
#     - If plan_code exists AND provider is Paystack → recurring plan (auto-renews)
#     - If user already has this plan → top-up (same endpoint)
#     Returns: { authorization_url, reference, access_code } for the
#     frontend to redirect/resume-inline.
#     """
#     plan = db.get(ServicePlan, plan_id)
#     if not plan or not plan.is_active:
#         raise NotFoundError("Plan", plan_id)

#     email = payload.email or user.email
#     ref = generate_reference("ST-SUB")

#     existing_sub = db.query(CustomerSubscription).options(joinedload(CustomerSubscription.plan)).filter(
#         CustomerSubscription.user_id == user.id,
#         CustomerSubscription.plan_id == plan_id,
#         CustomerSubscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.PAUSED]),
#     ).first()
#     is_topup = existing_sub is not None

#     resolved = _get_provider_for_org(db, user.organization_id)

#     payment = Payment(
#         user_id=user.id,
#         customer_subscription_id=existing_sub.id if existing_sub else None,
#         reference=ref,
#         provider=resolved.provider_name,
#         purpose=PaymentPurpose.TOP_UP if is_topup else PaymentPurpose.SUBSCRIPTION,
#         status=PaymentStatus.PENDING,
#         amount=plan.amount,
#         metadata_json={
#             "plan_id": str(plan.id),
#             "plan_name": plan.name,
#             "is_topup": is_topup,
#             "user_id": str(user.id),
#             "provider": resolved.provider_name,
#         },
#     )
#     db.add(payment); db.flush()

#     callback_url = payload.callback_url or get_app_config().payments_config.paystack.callback_url

#     try:
#         init_kwargs = dict(
#             email=email,
#             amount=plan.amount,
#             reference=ref,
#             callback_url=callback_url,
#             metadata={
#                 "plan_id": str(plan.id), "plan_name": plan.name,
#                 "is_topup": is_topup, "user_id": str(user.id),
#                 "payment_id": str(payment.id),
#             },
#             subaccount_code=resolved.subaccount_code,
#             key_fingerprint=resolved.key_fingerprint,
#         )
#         # Recurring plan codes are a Paystack-specific mechanism — only
#         # pass plan_code when Paystack is actually the resolved provider.
#         if resolved.provider_name == "paystack" and plan.paystack_plan_code:
#             init_kwargs["plan_code"] = plan.paystack_plan_code

#         ps_data = resolved.client.initialize_transaction(**init_kwargs)

#         payment.paystack_id = ps_data.get("access_code")
#         payment.access_code = ps_data.get("access_code")
#         payment.authorization_url = ps_data.get("authorization_url")

#         data = {
#             "reference": ref,
#             "authorization_url": ps_data.get("authorization_url"),
#             "access_code": ps_data.get("access_code"),
#             "is_topup": is_topup,
#             "provider": resolved.provider_name,
#             "plan": PlanOut.model_validate(plan),
#         }
#         logger.info(f"Initiated subscription payment: {data}")

#         return api_response(success=True, message="Payment initiated.", data=data)
#     except PaymentProviderError as exc:
#         payment.status = PaymentStatus.FAILED
#         raise CustomAPIException(f"Payment initiation failed: {exc.message}", 502, "PAYMENT_PROVIDER_ERROR")



# v3
@router.post("/payment/{plan_id}/paystack")
def initiate_subscription(
    plan_id: str,
    payload: SubscriptionInitiateRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Initiate subscription payment via the org's preferred payment provider
    (Organization.preferred_provider; Paystack if the user has no org or the
    org has no preference).
    - If plan_code exists AND provider is Paystack → recurring plan (auto-renews)
    - If user already has this plan → top-up (same endpoint)
    - The tenant payout split (subaccount) is resolved and self-healed inside
      initialize_with_recovery, including after the payment keys are switched.
    Returns: { authorization_url, reference, access_code } for the
    frontend to redirect/resume-inline.
    """
    plan = db.get(ServicePlan, plan_id)
    if not plan or not plan.is_active:
        raise NotFoundError("Plan", plan_id)

    email = payload.email or user.email
    ref = generate_reference("ST-SUB")

    existing_sub = db.query(CustomerSubscription).options(joinedload(CustomerSubscription.plan)).filter(
        CustomerSubscription.user_id == user.id,
        CustomerSubscription.plan_id == plan_id,
        CustomerSubscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.PAUSED]),
    ).first()
    is_topup = existing_sub is not None

    resolved = _get_provider_for_org(db, user.organization_id)

    payment = Payment(
        user_id=user.id,
        customer_subscription_id=existing_sub.id if existing_sub else None,
        reference=ref,
        provider=resolved.provider_name,
        purpose=PaymentPurpose.TOP_UP if is_topup else PaymentPurpose.SUBSCRIPTION,
        status=PaymentStatus.PENDING,
        amount=plan.amount,
        metadata_json={
            "plan_id": str(plan.id),
            "plan_name": plan.name,
            "is_topup": is_topup,
            "user_id": str(user.id),
            "provider": resolved.provider_name,
        },
    )
    db.add(payment); db.flush()

    callback_url = payload.callback_url or get_app_config().payments_config.paystack.callback_url

    try:
        # NOTE: no subaccount_code here. initialize_with_recovery reads it from
        # `resolved`; passing it as well would raise a duplicate-keyword TypeError.
        init_kwargs = dict(
            email=email,
            amount=plan.amount,
            reference=ref,
            callback_url=callback_url,
            metadata={
                "plan_id": str(plan.id), "plan_name": plan.name,
                "is_topup": is_topup, "user_id": str(user.id),
                "payment_id": str(payment.id),
            },
        )
        # Recurring plan codes are a Paystack-specific mechanism — only
        # pass plan_code when Paystack is actually the resolved provider.
        if resolved.provider_name == "paystack" and plan.paystack_plan_code:
            init_kwargs["plan_code"] = plan.paystack_plan_code

        recurring_skipped: Optional[str] = None
        try:
            ps_data = initialize_with_recovery(db, resolved, **init_kwargs)
        except PaymentProviderError as exc:
            # Plan codes belong to one Paystack account/mode, just like subaccounts.
            # If Paystack rejects the stored plan, take a one-time payment instead of
            # failing checkout. Auto-renewal is skipped and flagged for follow-up.
            if "plan_code" not in init_kwargs or "plan" not in exc.message.lower():
                raise
            logger.error("Paystack rejected plan %s (%s): %s", plan.id, plan.paystack_plan_code, exc.message)
            init_kwargs.pop("plan_code")
            recurring_skipped = "plan_rejected"
            init_kwargs["metadata"] = {**init_kwargs["metadata"], "recurring_skipped": recurring_skipped}
            ps_data = initialize_with_recovery(db, resolved, **init_kwargs)

        payment.paystack_id = ps_data.get("access_code")
        payment.access_code = ps_data.get("access_code")
        payment.authorization_url = ps_data.get("authorization_url")

        # Record any degradation so it can be reconciled later. Reassign the dict
        # (rather than mutating it) so SQLAlchemy sees the change.
        flags = {}
        if resolved.split_skipped_reason:
            flags["split_skipped"] = resolved.split_skipped_reason
        if recurring_skipped:
            flags["recurring_skipped"] = recurring_skipped
        if flags:
            payment.metadata_json = {**(payment.metadata_json or {}), **flags}

        data = {
            "reference": ref,
            "authorization_url": ps_data.get("authorization_url"),
            "access_code": ps_data.get("access_code"),
            "is_topup": is_topup,
            "provider": resolved.provider_name,
            "plan": PlanOut.model_validate(plan),
        }
        logger.info(f"Initiated subscription payment: {data}")

        return api_response(success=True, message="Payment initiated.", data=data)
    except PaymentProviderError as exc:
        payment.status = PaymentStatus.FAILED
        raise CustomAPIException(f"Payment initiation failed: {exc.message}", 502, "PAYMENT_PROVIDER_ERROR")
    except CustomAPIException:
        # e.g. 409 PAYOUT_ACCOUNT_INVALID from initialize_with_recovery
        payment.status = PaymentStatus.FAILED
        raise


@router.get("/payment/callback/paystack")
def paystack_callback(
    reference: str,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verify payment after Paystack redirects customer back."""
    return _verify_and_activate(reference, user, background, db)


@router.post("/payment/verify-inline/{plan_id}")
def verify_inline_payment(
    plan_id: str,
    reference: str,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verify after inline Paystack popup completes."""
    return _verify_and_activate(reference, user, background, db)


# def _verify_and_activate(reference: str, user: User, background: BackgroundTasks, db: Session):
#     """Shared logic: verify Paystack transaction → activate/top-up subscription."""
#     payment = db.query(Payment).filter(Payment.reference == reference).first()
#     if not payment:
#         raise NotFoundError("Payment", reference)

#     if payment.status == PaymentStatus.SUCCESS:
#         return api_response(
#             success=True,
#             message="Subscription already active.",
#         )

#     try:
#         tx = get_paystack().verify_transaction(reference)
#     except PaystackError as exc:
#         raise CustomAPIException(f"Payment verification failed: {exc.message}", 402, "PAYMENT_FAILED")

#     if tx.get("status") != "success":
#         payment.status = PaymentStatus.FAILED
#         raise CustomAPIException("Payment was not successful.", 402, "PAYMENT_NOT_SUCCESS")

#     # Update payment record
#     payment.status       = PaymentStatus.SUCCESS
#     payment.amount_paid  = __import__("app.utils.helpers", fromlist=["from_kobo"]).from_kobo(tx.get("amount", 0))
#     payment.channel      = tx.get("channel")
#     payment.paid_at      = datetime.now(timezone.utc)
#     payment.paystack_id  = str(tx.get("id", ""))
#     if tx.get("authorization"):
#         payment.card_type = tx["authorization"].get("card_type")
#         payment.bank      = tx["authorization"].get("bank")
#         payment.last4     = tx["authorization"].get("last4")

#     meta     = payment.metadata_json or {}
#     plan_id  = meta.get("plan_id")
#     is_topup = meta.get("is_topup", False)
#     plan     = db.get(ServicePlan, plan_id) if plan_id else None

#     if not plan:
#         raise CustomAPIException("Plan not found in payment metadata.", 500)

#     renewal  = next_renewal_date(plan.interval.value)
#     today    = datetime.now(timezone.utc).date()

#     existing = db.query(CustomerSubscription).filter(
#         CustomerSubscription.user_id == user.id,
#         CustomerSubscription.plan_id == plan.id,
#         CustomerSubscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.PAUSED, SubscriptionStatus.PENDING]),
#     ).first()

#     if existing and is_topup:
#         existing.top_up_reset(plan.units, renewal, reference)
#         payment.subscription_id = existing.id
#         sub = existing
#         msg = f"{plan.name} topped up! {plan.units} fresh units, billing reset from today."
#         background.add_task(notify_subscription_topped_up, db, user.id, plan.name, plan.units)
#     else:
#         sub = CustomerSubscription(
#             user_id=user.id, plan_id=plan.id,
#             status=SubscriptionStatus.ACTIVE,
#             units=plan.units, units_used=0,
#             subscribed_at=today, renews_at=renewal,
#             amount_paid=payment.amount_paid,
#             payment_reference=reference,
#             paystack_subscription_code=tx.get("plan_object", {}).get("subscription_code"),
#         )
#         db.add(sub); db.flush()
#         payment.subscription_id = sub.id
#         msg = f"Subscribed to {plan.name}! {plan.units} units added."
#         background.add_task(notify_subscription_activated, db, user.id, plan.name, plan.units)
#         background.add_task(send_subscription_activated,
#                             user.email, user.names, plan.name, plan.units, str(renewal))

#     return api_response(
#         success=True,
#         message=msg,
#         data={
#             "subscription": SubscriptionOut.from_orm_with_plan(sub),
#             "payment_reference": reference,
#             "is_topup": is_topup,
#         },
#     )




def _verify_and_activate(reference: str, user: User, background: BackgroundTasks, db: Session):
    """Shared logic: verify payment (against whichever provider actually
    processed it) → activate/top-up subscription."""
    payment = db.query(Payment).filter(Payment.reference == reference).first()
    if not payment:
        raise NotFoundError("Payment", reference)

    if payment.status == PaymentStatus.SUCCESS:
        return api_response(success=True, message="Subscription already active.")

    provider_client = get_provider(payment.provider)

    try:
        tx = provider_client.verify_transaction(reference)
    except PaymentProviderError as exc:
        raise CustomAPIException(f"Payment verification failed: {exc.message}", 402, "PAYMENT_FAILED")

    if tx.get("status") != "success":
        payment.status = PaymentStatus.FAILED
        raise CustomAPIException("Payment was not successful.", 402, "PAYMENT_NOT_SUCCESS")

    payment.status      = PaymentStatus.SUCCESS
    payment.amount_paid = from_kobo(tx.get("amount", 0))
    payment.channel     = tx.get("channel")
    payment.paid_at     = datetime.now(timezone.utc)
    payment.paystack_id = str(tx.get("id", ""))
    if tx.get("authorization"):
        payment.card_type = tx["authorization"].get("card_type")
        payment.bank      = tx["authorization"].get("bank")
        payment.last4     = tx["authorization"].get("last4")

    meta     = payment.metadata_json or {}
    plan_id  = meta.get("plan_id")
    is_topup = meta.get("is_topup", False)
    plan     = db.get(ServicePlan, plan_id) if plan_id else None

    if not plan:
        raise CustomAPIException("Plan not found in payment metadata.", 500)

    renewal = next_renewal_date(plan.interval.value)
    today   = datetime.now(timezone.utc).date()

    existing = db.query(CustomerSubscription).filter(
        CustomerSubscription.user_id == user.id,
        CustomerSubscription.plan_id == plan.id,
        CustomerSubscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.PAUSED, SubscriptionStatus.PENDING]),
    ).first()

    if existing and is_topup:
        existing.top_up_reset(plan.units, renewal, reference)
        payment.subscription_id = existing.id
        sub = existing
        msg = f"{plan.name} topped up! {plan.units} fresh units, billing reset from today."
        background.add_task(notify_subscription_topped_up, db, user.id, plan.name, plan.units)
    else:
        sub = CustomerSubscription(
            user_id=user.id, plan_id=plan.id,
            status=SubscriptionStatus.ACTIVE,
            units=plan.units, units_used=0,
            subscribed_at=today, renews_at=renewal,
            amount_paid=payment.amount_paid,
            payment_reference=reference,
            paystack_subscription_code=tx.get("plan_object", {}).get("subscription_code"),
        )
        db.add(sub); db.flush()
        payment.subscription_id = sub.id
        msg = f"Subscribed to {plan.name}! {plan.units} units added."
        background.add_task(notify_subscription_activated, db, user.id, plan.name, plan.units)
        background.add_task(
            send_subscription_activated,
            user.email, user.names, plan.name, 
            plan.units, str(renewal)
        )

    return api_response(
        success=True,
        message=msg,
        data={
            "subscription": SubscriptionOut.from_orm_with_plan(sub),
            "payment_reference": reference,
            "is_topup": is_topup,
        },
    )


@router.post("/{sub_id}/cancel")
def cancel_subscription(
    sub_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = db.query(CustomerSubscription).filter(CustomerSubscription.id == sub_id, CustomerSubscription.user_id == user.id).first()
    if not sub:
        raise NotFoundError("Subscription", sub_id)
    if sub.status == SubscriptionStatus.CANCELED:
        return api_response(success=True, message="Subscription already cancelled.")

    # Cancel on Paystack if we have a code
    # if sub.paystack_subscription_code and sub.paystack_email_token:
    #     try:
    #         get_paystack().disable_subscription(sub.paystack_subscription_code, sub.paystack_email_token)
    #     except PaystackError as exc:
    #         logger.warning("Paystack cancel failed: %s", exc)
    # v2
    if sub.paystack_subscription_code and sub.paystack_email_token:
        try:
            get_paystack().disable_subscription(sub.paystack_subscription_code, sub.paystack_email_token)
        except PaystackError as exc:
            logger.warning("Paystack cancel failed: %s", exc)
    elif sub.paystack_subscription_code:
        logger.warning(
            "Cancelling subscription %s locally, but no paystack_email_token yet — "
            "Paystack-side billing may continue until the subscription.create webhook arrives.",
            sub.id,
        )
    
    sub.status       = SubscriptionStatus.CANCELED
    sub.cancelled_at = datetime.now(timezone.utc)
    return api_response(
        success=True,
        message="Subscription cancelled. Remaining units are still usable until period end.",
        data=SubscriptionOut.from_orm_with_plan(sub),
    )


@router.post("/{sub_id}/pause")
def pause_subscription(
    sub_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = db.query(CustomerSubscription).filter(CustomerSubscription.id == sub_id, CustomerSubscription.user_id == user.id).first()
    if not sub:
        raise NotFoundError("Subscription", sub_id)
    if sub.status != SubscriptionStatus.ACTIVE:
        raise CustomAPIException("Only active subscriptions can be paused.", 400)
    if sub.paystack_subscription_code and sub.paystack_email_token:
        try:
            get_paystack().disable_subscription(sub.paystack_subscription_code, sub.paystack_email_token)
        except PaystackError as exc:
            logger.warning("Paystack pause failed: %s", exc)
    sub.status = SubscriptionStatus.PAUSED
    return api_response(
        success=True,
        message="Subscription paused. No further charges.",
        data=SubscriptionOut.from_orm_with_plan(sub),
    )


@router.post("/{sub_id}/resume")
def resume_subscription(
    sub_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = db.query(CustomerSubscription).filter(CustomerSubscription.id == sub_id, CustomerSubscription.user_id == user.id).first()
    if not sub:
        raise NotFoundError("Subscription", sub_id)
    if sub.status != SubscriptionStatus.PAUSED:
        raise CustomAPIException("Only paused subscriptions can be resumed.", 400)
    if sub.paystack_subscription_code and sub.paystack_email_token:
        try:
            get_paystack().enable_subscription(sub.paystack_subscription_code, sub.paystack_email_token)
        except PaystackError as exc:
            logger.warning("Paystack resume failed: %s", exc)
    sub.status = SubscriptionStatus.ACTIVE
    return api_response(
        success=True,
        message="Subscription resumed.",
        data=SubscriptionOut.from_orm_with_plan(sub),
    )


@router.get("/{sub_id}/manage-link")
def get_manage_link(
    sub_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = db.query(CustomerSubscription).filter(CustomerSubscription.id == sub_id, CustomerSubscription.user_id == user.id).first()
    if not sub:
        raise NotFoundError("Subscription", sub_id)
    link = None
    if sub.paystack_subscription_code:
        link = get_paystack().get_subscription_manage_link(sub.paystack_subscription_code)
    return api_response(
        success=True,
        message="Management link fetched.",
        data={"link": link or "https://app.paystack.com"},
    )


# ─── USAGE ────────────────────────────────────────────────────────────────────

@router.get("/usage/statistics")
def usage_statistics(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    subs = (db.query(CustomerSubscription)
            .options(joinedload(CustomerSubscription.plan))
            .filter(CustomerSubscription.user_id == user.id,
                    CustomerSubscription.status == SubscriptionStatus.ACTIVE).all())
    total  = sum(s.units for s in subs)
    used   = sum(s.units_used for s in subs)
    remain = sum(s.units_remaining for s in subs)
    pct    = round((used / total * 100), 1) if total else 0.0
    return api_response(
        success=True,
        message="Usage statistics fetched.",
        data=CustomerUsageStatsOut(
            total_units=total, units_used=used, remaining_units=remain,
            usage_percentage=pct,
            subscriptions=[SubscriptionOut.from_orm_with_plan(s) for s in subs],
        ),
    )


@router.get("/usage")
def list_usage(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    mine: bool = False,
    user_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List usage logs. Staff/admin can filter by user_id, customers can only see their own."""
    try:
        q = db.query(CustomerUsageLog)
        # if mine or current_user.role.value == "customer":
        if mine or current_user.has_role("customer"):
            q = q.filter(CustomerUsageLog.user_id == current_user.id)
        elif user_id:
            q = q.filter(CustomerUsageLog.user_id == user_id)
        total = q.count()
        logs  = q.order_by(desc(CustomerUsageLog.created_at)).offset((page-1)*page_size).limit(page_size).all()
        items = []
        for log in logs:
            out = CustomerUsageLogOut.model_validate(log)
            if log.user:
                out.user.names     = log.user.names
                # out.user_username = log.user.username
            if log.recorded_by:
                out.recorded_by_name = log.recorded_by.names
            items.append(out)
        return api_response(
            success=True,
            message="Usage logs fetched.",
            data={
                "items": items,
                "page": page,
                "page_size": page_size,
                "total": total,
            },
        )
    except Exception as exc:
        logger.exception("Error listing usage logs: %s", exc)
        raise CustomAPIException("Could not fetch usage logs.", 500, "USAGE_LIST_ERROR")

@router.post("/usage")
def record_usage(
    payload: UsageRecordRequest,
    background: BackgroundTasks,
    staff: User = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
):
    """
    Staff/admin records unit deduction when garments are received.
    Supports single subscription or merged across multiple subscriptions.
    """
    target_user = db.get(User, payload.user_id)
    if not target_user:
        raise NotFoundError("User", payload.user_id)

    if payload.payment_method == UsagePaymentSource.SUBSCRIPTION:
        # Merged across multiple subs?
        if payload.sub_allocations:
            return _record_merged_usage(payload, target_user, staff, background, db)
        else:
            return _record_single_usage(payload, target_user, staff, background, db)
    else:
        # Direct / cash — just log, no unit deduction
        log = CustomerUsageLog(
            user_id=target_user.id,
            recorded_by_id=staff.id,
            units_deducted=0,
            source=payload.payment_method,
            description=payload.description or f"Direct payment — {payload.order_reference or ''}",
            notes=payload.notes,
            balance_before=0,
            balance_after=0,
            total_units_snapshot=0,
            payment_amount=payload.payment_amount,
            order_id=payload.order_id,
        )
        db.add(log); db.flush()
        return api_response(
            success=True,
            message="Usage recorded (direct payment).",
            data=CustomerUsageLogOut.model_validate(log),
            status_code=201,
        )


def _record_single_usage(
    payload: UsageRecordRequest,
    user: User,
    staff: User,
    background: BackgroundTasks,
    db: Session,
):
    sub = db.query(CustomerSubscription).options(joinedload(CustomerSubscription.plan)).filter(
        CustomerSubscription.id == payload.subscription_id,
        CustomerSubscription.user_id == user.id,
        CustomerSubscription.status == SubscriptionStatus.ACTIVE,
    ).first()
    if not sub:
        raise NotFoundError("Active subscription", payload.subscription_id)
    if sub.units_remaining < payload.units_used:
        raise InsufficientUnitsError(payload.units_used, sub.units_remaining)

    before = sub.units_remaining
    sub.units_used += payload.units_used

    log = CustomerUsageLog(
        user_id=user.id,
        subscription_id=sub.id,
        recorded_by_id=staff.id,
        order_id=payload.order_id,
        units_deducted=payload.units_used,
        source=UsagePaymentSource.SUBSCRIPTION,
        plan_name=sub.plan.name if sub.plan else None,
        description=payload.description or f"{payload.units_used} garments received",
        notes=payload.notes,
        balance_before=before,
        balance_after=sub.units_remaining,
        total_units_snapshot=sub.units,
    )
    db.add(log); db.flush()

    if sub.units_remaining <= 20:
        background.add_task(notify_low_units, db, user.id, sub.plan.name if sub.plan else "", sub.units_remaining)

    return api_response(
        success=True,
        message="Usage recorded.",
        data=CustomerUsageLogOut.model_validate(log),
        status_code=201,
    )


def _record_merged_usage(
    payload: UsageRecordRequest,
    user: User,
    staff: User,
    background: BackgroundTasks,
    db: Session,
):
    alloc_total = sum(a.units for a in payload.sub_allocations)
    if alloc_total < payload.units_used:
        raise CustomAPIException(
            f"Allocated {alloc_total} units but {payload.units_used} required.", 400
        )

    breakdown = []
    for alloc in payload.sub_allocations:
        sub = db.query(CustomerSubscription).options(joinedload(CustomerSubscription.plan)).filter(
            CustomerSubscription.id == alloc.subscription_id,
            CustomerSubscription.user_id == user.id,
            CustomerSubscription.status == SubscriptionStatus.ACTIVE,
        ).first()
        if not sub:
            raise NotFoundError("Active subscription", alloc.subscription_id)
        if sub.units_remaining < alloc.units:
            raise InsufficientUnitsError(alloc.units, sub.units_remaining)
        sub.units_used += alloc.units
        breakdown.append({"plan_id": sub.plan_id, "plan_name": sub.plan.name if sub.plan else "", "units": alloc.units})

    # Aggregate totals for the log entry
    total_remaining_all = sum(
        db.query(CustomerSubscription).get(a.subscription_id).units_remaining
        for a in payload.sub_allocations
    )
    log = CustomerUsageLog(
        user_id=user.id,
        recorded_by_id=staff.id,
        order_id=payload.order_id,
        units_deducted=payload.units_used,
        source=UsagePaymentSource.SUBSCRIPTION,
        plan_name="Multiple Plans",
        description=payload.description or f"{payload.units_used} garments received (merged)",
        notes=payload.notes,
        balance_before=total_remaining_all + payload.units_used,
        balance_after=total_remaining_all,
        total_units_snapshot=sum(db.query(CustomerSubscription).get(a.subscription_id).units for a in payload.sub_allocations),
        is_merged=True,
        merge_breakdown=breakdown,
    )
    db.add(log); db.flush()
    return api_response(
        success=True,
        message="Merged usage recorded.",
        data=CustomerUsageLogOut.model_validate(log),
        status_code=201,
    )
