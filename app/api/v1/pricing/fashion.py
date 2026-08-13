# app/api/v1/pricing.py
"""app/api/v1/pricing.py — Garment types, laundry services, delivery areas."""
from decimal import Decimal
from fastapi import APIRouter, Depends, BackgroundTasks
from app.api.deps.rbac import require_roles
from app.models.orders import FashionOrder, Order, OrderStatusHistory
from app.schemas.orders import FashionOrderCreate
from app.services.notification_service import notify_order_status
from app.enums.stitch import FashionStatus, OrderType, PaymentMethodType
from app.utils.helpers import generate_order_reference
from app.api.v1.orders import _calc_fashion_fees
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.api.deps.auth import get_current_user
from app.core.exceptions.custom_exceptions import BadRequestError, CustomAPIException, NotFoundError
from app.db.database import get_db
from app.models.pricing import FashionService, FashionServiceOverride, FashionFeeSettings
from app.models.users import User
from app.schemas.pricing import (
    FashionServiceCreate, FashionServiceOut, FashionServiceUpdate,
)
from app.utils.responses import api_response

router = APIRouter(tags=["Pricing"])

# ─── Fashion Fee Settings ─────────────────────────────────────────────────────
from app.models.pricing import FashionFeeSettings
from app.schemas.pricing import FashionFeeSettingsOut, FashionFeeSettingsUpdate

def _get_or_create_fashion_fees(db: Session, organization_id: str) -> FashionFeeSettings:
    fees = db.query(FashionFeeSettings).filter(
        FashionFeeSettings.organization_id == organization_id
    ).first()
    if not fees:
        fees = FashionFeeSettings(organization_id=organization_id)
        db.add(fees)
        db.flush()
    return fees

# def _effective_fashion_services(db: Session, organization_id: str, include_inactive: bool = False):
#     """Global defaults (minus any this org has explicitly hidden) + this
#         org's own services — the single source of truth for what a customer
#         sees and what create_fashion_order validates against."""
#     hidden_ids = {
#         row.fashion_service_id for row in db.query(FashionServiceOverride.fashion_service_id).filter(
#             FashionServiceOverride.organization_id == organization_id
#         ).all()
#     }

#     q = db.query(FashionService).filter(
#         FashionService.deleted == False,   # ← this was missing — the actual root cause
#         or_(FashionService.organization_id.is_(None), FashionService.organization_id == organization_id),
#     )
#     if not include_inactive:
#         q = q.filter(FashionService.is_active.isnot(False)) # noqa: E712

#     services = q.order_by(FashionService.display_order, FashionService.name).all()
#     return [s for s in services if not (s.organization_id is None and s.id in hidden_ids)]

# app/api/v1/pricing.py

def _effective_fashion_services(db: Session, organization_id: str, include_inactive: bool = False):
    hidden_ids = {
        row.fashion_service_id for row in db.query(FashionServiceOverride.fashion_service_id).filter(
            FashionServiceOverride.organization_id == organization_id
        ).all()
    }
    q = db.query(FashionService).filter(
        FashionService.deleted == False,
        or_(FashionService.organization_id.is_(None), FashionService.organization_id == organization_id),
    )
    if not include_inactive:
        q = q.filter(FashionService.is_active.isnot(False))

    services = q.order_by(FashionService.display_order, FashionService.name).all()

    if include_inactive:
        # Admin/management context: keep hidden defaults in the list instead
        # of dropping them, so they can still be restored. Represent "hidden
        # for this org" as is_active=False on the returned object — the
        # underlying row's real is_active is untouched.
        result = []
        for s in services:
            if s.organization_id is None and s.id in hidden_ids:
                s.is_active = False  # display-only override, not persisted (no commit here)
            result.append(s)
        return result

    # Customer-facing context: hidden defaults are fully excluded, as before.
    return [s for s in services if not (s.organization_id is None and s.id in hidden_ids)]

@router.get("/fashion-fees")
def get_fashion_fees(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fees = _get_or_create_fashion_fees(db, user.organization_id)
    return api_response(True, "Fashion fees fetched.", data=FashionFeeSettingsOut.model_validate(fees))

# @router.put("/fashion-fees", dependencies=[Depends(require_roles("admin", "super_admin"))])
# def update_fashion_fees(
#     payload: FashionFeeSettingsUpdate,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     fees = _get_or_create_fashion_fees(db, user.organization_id)
#     for k, v in payload.model_dump(exclude_none=True).items():
#         setattr(fees, k, v)
#     db.commit()
#     db.refresh(fees)
#     return api_response(True, "Fashion fees updated.", data=FashionFeeSettingsOut.model_validate(fees))

@router.put("/fashion-fees", dependencies=[Depends(require_roles("admin", "super_admin"))])
def update_fashion_fees(
    payload: FashionFeeSettingsUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fees = _get_or_create_fashion_fees(db, user.organization_id)
    data = payload.model_dump(exclude_unset=True)   # exclude_unset, NOT exclude_none —
    # a deliberately-sent empty list [] or a real applies_to list must NOT be dropped,
    # which exclude_none would risk if any edge case sends None meaningfully.
    for k, v in data.items():
        setattr(fees, k, v)
    db.commit()
    db.refresh(fees)
    return api_response(True, "Fashion fees updated.", data=FashionFeeSettingsOut.model_validate(fees))


# @router.post("/fashion-orders", status_code=201)
# def create_fashion_order(
#     payload: FashionOrderCreate,
#     background: BackgroundTasks,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     customer_id = user.id
#     behalf_id = None
#     if payload.behalf_user_id and user.has_role("admin", "staff"):
#         behalf_id = payload.behalf_user_id
#         customer_id = payload.behalf_user_id

#     # ── Server-side fee calculation from admin-configured settings —
#     # never trust client-submitted fee amounts.
#     fees = _get_or_create_fashion_fees(db, user.organization_id)

#     consultation_fee = fees.consultation_fee if fees.consultation_fee_enabled else Decimal("0")
#     material_pickup_fee = (
#         fees.material_pickup_fee
#         if payload.service_type == "Material Pickup" and fees.material_pickup_fee_enabled
#         else Decimal("0")
#     )
#     total = consultation_fee + material_pickup_fee

#     if payload.total_amount and abs(Decimal(str(payload.total_amount)) - total) > Decimal("0.01"):
#         raise CustomAPIException("Order total mismatch. Please refresh and try again.", 400)

#     ref = generate_order_reference("FS")

#     # Same payment-recording pattern as laundry orders — a payment_reference
#     # present on a DIRECT-method request means the frontend already
#     # completed/verified the Paystack charge inline before submitting.
#     is_paid_inline = bool(payload.payment_reference) and payload.payment_method == PaymentMethodType.DIRECT

#     order = Order(
#         reference=ref,
#         order_type=OrderType.FASHION,
#         customer_id=customer_id,
#         behalf_user_id=behalf_id,
#         created_by_id=user.id,
#         delivery_address=payload.delivery_address,
#         priority=payload.priority,
#         payment_method=payload.payment_method,
#         payment_status="paid" if is_paid_inline else ("free" if total == 0 else "pending"),
#         payment_reference=payload.payment_reference,
#         total_amount=total,
#         status=FashionStatus.CONSULTATION.value,
#     )
#     db.add(order)
#     db.flush()

#     db.add(FashionOrder(
#         id=order.id,
#         order_id=order.id,
#         fashion_status=FashionStatus.CONSULTATION,
#         service_type=payload.service_type,
#         item_name=payload.item_name,
#         fabric_source=payload.fabric_source,
#         measurements=payload.measurements.model_dump() if payload.measurements else None,
#         design_notes=payload.design_notes,
#         reference_images=payload.reference_images,
#         consultation_date=payload.consultation_date,
#         consultation_fee=consultation_fee,
#         material_pickup_fee=material_pickup_fee,
#     ))
#     db.add(OrderStatusHistory(
#         order_id=order.id, from_status=None,
#         to_status=FashionStatus.CONSULTATION.value,
#         changed_by_id=user.id, notes="Fashion order created",
#     ))
#     db.flush()

#     customer = db.get(User, customer_id)
#     if customer:
#         background.add_task(notify_order_status, db, customer_id, ref, FashionStatus.CONSULTATION.value)

#     return api_response(
#         True, "Fashion order created.",
#         data={"id": order.id, "reference": ref, "total_amount": float(total)},
#         status_code=201,
#     )

# # v2
# @router.post("/fashion-orders", status_code=201)
# def create_fashion_order(
#     payload: FashionOrderCreate,
#     background: BackgroundTasks,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     customer_id = user.id
#     behalf_id = None
#     if payload.behalf_user_id and user.has_role("admin", "staff"):
#         behalf_id = payload.behalf_user_id
#         customer_id = payload.behalf_user_id

#     # ── Validate every selected service against the org's EFFECTIVE
#     # catalog — global defaults minus anything they've hidden, plus their
#     # own additions. This is the exact same set the customer was shown
#     # when picking services, so nothing here can silently reject a
#     # legitimately-offered service.
#     if not payload.service_types:
#         raise BadRequestError("At least one service must be selected.")

#     effective_services = _effective_fashion_services(db, user.organization_id)
#     valid_names = {s.name for s in effective_services}
#     invalid = set(payload.service_types) - valid_names
#     if invalid:
#         raise CustomAPIException(f"Unknown or inactive service(s): {', '.join(sorted(invalid))}", 400)

#     # ── Fee calculation — driven entirely by admin-configured fee
#     # settings and their applies_to lists, never a hardcoded service
#     # name match.
#     fees = _get_or_create_fashion_fees(db, user.organization_id)
#     consultation_fee, material_pickup_fee = _calc_fashion_fees(fees, payload.service_types)
#     total = consultation_fee + material_pickup_fee

#     if payload.total_amount and abs(Decimal(str(payload.total_amount)) - total) > Decimal("0.01"):
#         raise CustomAPIException("Order total mismatch. Please refresh and try again.", 400)

#     is_paid_inline = bool(payload.payment_reference) and payload.payment_method == PaymentMethodType.DIRECT
#     payment_status = "paid" if is_paid_inline else ("free" if total == 0 else "pending")

#     ref = generate_order_reference("FS")
#     order = Order(
#         reference=ref,
#         order_type=OrderType.FASHION,
#         customer_id=customer_id,
#         behalf_user_id=behalf_id,
#         created_by_id=user.id,
#         delivery_address=payload.delivery_address,
#         priority=payload.priority,
#         payment_method=payload.payment_method,
#         payment_status=payment_status,
#         payment_reference=payload.payment_reference,
#         total_amount=total,
#         status=FashionStatus.CONSULTATION.value,
#     )
#     db.add(order)
#     db.flush()

#     db.add(FashionOrder(
#         id=order.id,
#         order_id=order.id,
#         fashion_status=FashionStatus.CONSULTATION,
#         service_types=payload.service_types or [],
#         item_name=payload.item_name,
#         fabric_source=payload.fabric_source,
#         measurements=payload.measurements.model_dump() if payload.measurements else None,
#         design_notes=payload.design_notes,
#         reference_images=payload.reference_images,
#         consultation_date=payload.consultation_date,
#         consultation_time=payload.consultation_time,
#         consultation_fee=consultation_fee,
#         material_pickup_fee=material_pickup_fee,
#     ))
#     db.add(OrderStatusHistory(
#         order_id=order.id, from_status=None,
#         to_status=FashionStatus.CONSULTATION.value,
#         changed_by_id=user.id, notes="Fashion order created",
#     ))
#     db.flush()

#     customer = db.get(User, customer_id)
#     if customer:
#         background.add_task(notify_order_status, db, customer_id, ref, FashionStatus.CONSULTATION.value)

#     return api_response(
#         True, "Fashion order created.",
#         data={"id": order.id, "reference": ref, "total_amount": float(total)},
#         status_code=201,
#     )

# # v3
# @router.post("/fashion-orders", status_code=201)
# def create_fashion_order(
#     payload: FashionOrderCreate,
#     background: BackgroundTasks,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     customer_id = user.id
#     behalf_id = None
#     if payload.behalf_user_id and user.has_role("admin", "staff"):
#         behalf_id = payload.behalf_user_id
#         customer_id = payload.behalf_user_id

#     # ── Validate against effective catalog (global + org-specific) ──
#     if not payload.service_types:
#         raise BadRequestError("At least one service must be selected.")

#     effective_services = _effective_fashion_services(db, user.organization_id)
#     valid_names = {s.name for s in effective_services}
#     invalid = set(payload.service_types) - valid_names
#     if invalid:
#         raise CustomAPIException(
#             f"Unknown or inactive service(s): {', '.join(sorted(invalid))}", 400
#         )

#     # ── Fee calculation (server-side only) ──
#     fees = _get_or_create_fashion_fees(db, user.organization_id)
#     consultation_fee, material_pickup_fee = _calc_fashion_fees(fees, payload.service_types)
#     total = consultation_fee + material_pickup_fee

#     if payload.total_amount and abs(Decimal(str(payload.total_amount)) - total) > Decimal("0.01"):
#         raise CustomAPIException("Order total mismatch. Please refresh and try again.", 400)

#     is_paid_inline = bool(payload.payment_reference) and payload.payment_method == PaymentMethodType.DIRECT
#     payment_status = "paid" if is_paid_inline else ("free" if total == 0 else "pending")

#     ref = generate_order_reference("FS")
#     order = Order(
#         reference=ref,
#         order_type=OrderType.FASHION,
#         customer_id=customer_id,
#         behalf_user_id=behalf_id,
#         created_by_id=user.id,
#         delivery_address=payload.delivery_address,
#         priority=payload.priority,
#         payment_method=payload.payment_method,
#         payment_status=payment_status,
#         payment_reference=payload.payment_reference,
#         total_amount=total,
#         status=FashionStatus.CONSULTATION.value,
#     )
#     db.add(order)
#     db.flush()

#     db.add(FashionOrder(
#         id=order.id,
#         order_id=order.id,
#         fashion_status=FashionStatus.CONSULTATION,
#         service_types=payload.service_types or [],
#         item_name=payload.item_name,
#         fabric_source=payload.fabric_source,
#         measurements=payload.measurements.model_dump() if payload.measurements else None,
#         design_notes=payload.design_notes,
#         reference_images=payload.reference_images,
#         consultation_date=payload.consultation_date,
#         consultation_time=payload.consultation_time,
#         consultation_fee=consultation_fee,
#         material_pickup_fee=material_pickup_fee,
#     ))
#     db.add(OrderStatusHistory(
#         order_id=order.id,
#         from_status=None,
#         to_status=FashionStatus.CONSULTATION.value,
#         changed_by_id=user.id,
#         notes="Fashion order created",
#     ))
#     db.flush()

#     customer = db.get(User, customer_id)
#     if customer:
#         background.add_task(notify_order_status, db, customer_id, ref, FashionStatus.CONSULTATION.value)

#     return api_response(
#         True,
#         "Fashion order created.",
#         data={"id": order.id, "reference": ref, "total_amount": float(total)},
#         status_code=201,
#     )


# @router.get("/fashion-services")
# def list_fashion_services(
#     include_inactive: bool = False,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     # Global defaults (organization_id IS NULL) + this org's own additions,
#     # merged into one list — exactly the pattern used for laundry services.
#     q = db.query(FashionService).filter(
#         or_(FashionService.organization_id.is_(None), FashionService.organization_id == user.organization_id)
#     )
#     if not include_inactive:
#         q = q.filter(FashionService.is_active == True)  # noqa: E712
#     services = q.order_by(FashionService.display_order, FashionService.name).all()
#     return api_response(True, "Fashion services fetched.", data=[FashionServiceOut.model_validate(s) for s in services])

# v2
# @router.get("/fashion-services")
# def list_fashion_services(
#     include_inactive: bool = False,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     services = _effective_fashion_services(db, user.organization_id, include_inactive)
#     return api_response(True, "Fashion services fetched.", data=[FashionServiceOut.model_validate(s) for s in services])
# 
@router.get("/fashion-services")
def list_fashion_services(
    include_inactive: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services = _effective_fashion_services(db, user.organization_id, include_inactive)
    out = []
    for s in services:
        item = FashionServiceOut.model_validate(s)
        item.is_global = s.organization_id is None   # ← this line was missing
        out.append(item)
    return api_response(True, "Fashion services fetched.", data=out)


@router.post("/fashion-services/{service_id}/hide", dependencies=[Depends(require_roles("admin", "super_admin"))])
def hide_default_fashion_service(
    service_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    svc = db.query(FashionService).filter(FashionService.id == service_id, FashionService.organization_id.is_(None)).first()
    if not svc:
        raise NotFoundError("Global fashion service", service_id)
    exists = db.query(FashionServiceOverride).filter(
        FashionServiceOverride.organization_id == user.organization_id,
        FashionServiceOverride.fashion_service_id == service_id,
    ).first()
    if not exists:
        db.add(FashionServiceOverride(organization_id=user.organization_id, fashion_service_id=service_id))
        db.commit()
    return api_response(True, "Default service hidden for your organization.")


@router.post("/fashion-services/{service_id}/unhide", dependencies=[Depends(require_roles("admin", "super_admin"))])
def unhide_default_fashion_service(
    service_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(FashionServiceOverride).filter(
        FashionServiceOverride.organization_id == user.organization_id,
        FashionServiceOverride.fashion_service_id == service_id,
    ).delete()
    db.commit()
    return api_response(True, "Default service restored.")


@router.post("/fashion-services", status_code=201, dependencies=[Depends(require_roles("admin", "super_admin"))])
def create_fashion_service(
    payload: FashionServiceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Always created scoped to the admin's own org — never global.
    # Global defaults are only ever seeded via the one-off script, never
    # created through this tenant-facing endpoint.
    svc = FashionService(organization_id=user.organization_id, **payload.model_dump())
    db.add(svc); db.flush()
    return api_response(True, "Fashion service created.", data=FashionServiceOut.model_validate(svc), status_code=201)


@router.put("/fashion-services/{service_id}", dependencies=[Depends(require_roles("admin", "super_admin"))])
def update_fashion_service(
    service_id: str,
    payload: FashionServiceUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Deliberately scoped to organization_id == user's own org — an admin
    # can never edit a global default (organization_id IS NULL) through
    # this endpoint, since that would silently change it for every tenant
    # on the platform. If they want a different version of a default
    # service, they create their own org-specific entry with the same
    # or a different name instead.
    svc = db.query(FashionService).filter(
        FashionService.id == service_id, FashionService.organization_id == user.organization_id
    ).first()
    if not svc:
        raise NotFoundError("Fashion service", service_id)
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(svc, k, v)
    db.commit(); db.refresh(svc)
    return api_response(True, "Fashion service updated.", data=FashionServiceOut.model_validate(svc))

# v2
@router.delete("/fashion-services/{service_id}", dependencies=[Depends(require_roles("admin", "super_admin"))])
def delete_fashion_service(
    service_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    svc = db.query(FashionService).filter(
        FashionService.id == service_id, FashionService.organization_id == user.organization_id
    ).first()
    if not svc:
        raise NotFoundError("Fashion service", service_id)
    svc.deleted = True   # StitchBase's soft-delete column — clean assignment, no ternary
    db.commit()
    return api_response(True, "Fashion service removed.")

@router.delete("/fashion-services/{service_id}", dependencies=[Depends(require_roles("admin", "super_admin"))])
def delete_fashion_service(
    service_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    svc = db.query(FashionService).filter(
        FashionService.id == service_id, FashionService.organization_id == user.organization_id
    ).first()
    if not svc:
        raise NotFoundError("Fashion service", service_id)
    svc.deleted = True if hasattr(svc, "deleted") else None
    db.delete(svc) if not hasattr(svc, "deleted") else None
    db.commit()
    return api_response(True, "Fashion service removed.")

