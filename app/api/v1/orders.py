# # """app/api/v1/orders.py — Laundry and Fashion order endpoints."""

# # v2
# """app/api/v1/orders.py — Laundry and Fashion order endpoints."""
# import logging
# from decimal import Decimal
# from typing import Optional

# from fastapi import APIRouter, BackgroundTasks, Depends, Query
# from sqlalchemy import desc, or_
# from sqlalchemy.orm import Session, joinedload

# from app.api.deps.users import get_current_user, get_db
# from app.api.deps.rbac import require_roles
# from app.core.exceptions.custom_exceptions import CustomAPIException, ForbiddenError, NotFoundError
# from app.enums.stitch import (
#     LaundryStatus, FashionStatus, OrderPriority, OrderType,
#     PaymentMethodType,
# )
# from app.enums.billing import SubscriptionStatus

# from app.models.orders import (
#     FashionOrder, LaundryOrder, Order, OrderGarmentItem, OrderStatusHistory,
# )

# from app.models.tenant_billing import ServicePlan, CustomerSubscription
# from app.models.users import User
# from app.schemas.orders import (
#     FashionOrderCreate, FashionOrderOut, FashionOrderUpdate,
#     LaundryOrderCreate, LaundryOrderOut, LaundryOrderUpdate,
#     OrderStatusUpdate, StatusHistoryOut, GarmentItemOut,
# )
# from app.services.email_service import send_order_confirmed, send_order_status_update
# from app.services.notification_service import notify_order_status
# from app.utils.helpers import generate_order_reference
# from app.utils.responses import api_response

# logger = logging.getLogger(__name__)
# router = APIRouter(tags=["Orders"])


# def _enrich_laundry(order: Order) -> LaundryOrderOut:
#     return LaundryOrderOut(
#         id=order.id, reference=order.reference,
#         customer_id=order.customer_id,
#         customer_name=order.customer.names if order.customer else None,
#         customer_phone=order.customer.phone if order.customer else None,
#         status=order.status,
#         laundry_status=order.laundry_detail.laundry_status if order.laundry_detail else None,
#         priority=order.priority,
#         payment_method=order.payment_method,
#         payment_status=order.payment_status,
#         pickup_date=order.pickup_date,
#         pickup_time=order.pickup_time,
#         delivery_area=order.delivery_area.name if order.delivery_area else None,
#         delivery_address=order.delivery_address,
#         garment_subtotal=order.garment_subtotal,
#         priority_surcharge=order.priority_surcharge,
#         delivery_fee=order.delivery_fee,
#         total_amount=order.total_amount,
#         garment_count=order.laundry_detail.garment_count if order.laundry_detail else None,
#         garment_items=[GarmentItemOut.model_validate(g) for g in order.garment_items],
#         status_history=[
#             StatusHistoryOut(
#                 id=h.id, from_status=h.from_status, to_status=h.to_status,
#                 notes=h.notes, is_reversal=h.is_reversal, created_at=h.created_at,
#                 changed_by_name=h.changed_by.names if h.changed_by else None,
#             ) for h in order.status_history
#         ],
#         services_json=order.laundry_detail.services_json if order.laundry_detail else None,
#         special_instructions=order.special_instructions,
#         created_at=order.created_at,
#         updated_at=order.updated_at,
#     )


# def _enrich_fashion(order: Order) -> FashionOrderOut:
#     fd = order.fashion_detail
#     return FashionOrderOut(
#         id=order.id, reference=order.reference,
#         customer_id=order.customer_id,
#         customer_name=order.customer.names if order.customer else None,
#         customer_phone=order.customer.phone if order.customer else None,
#         status=order.status,
#         fashion_status=fd.fashion_status if fd else None,
#         service_type=fd.service_type if fd else None,
#         item_name=fd.item_name if fd else None,
#         fabric_source=fd.fabric_source if fd else None,
#         measurements=fd.measurements if fd else None,
#         design_notes=fd.design_notes if fd else None,
#         reference_images=fd.reference_images if fd else None,
#         priority=order.priority,
#         payment_method=order.payment_method,
#         payment_status=order.payment_status,
#         total_amount=order.total_amount,
#         consultation_date=fd.consultation_date if fd else None,
#         fitting_date=fd.fitting_date if fd else None,
#         delivery_address=order.delivery_address,
#         status_history=[
#             StatusHistoryOut(
#                 id=h.id, from_status=h.from_status, to_status=h.to_status,
#                 notes=h.notes, is_reversal=h.is_reversal, created_at=h.created_at,
#                 changed_by_name=h.changed_by.names if h.changed_by else None,
#             ) for h in order.status_history
#         ],
#         created_at=order.created_at,
#         updated_at=order.updated_at,
#     )


# def _get_order_or_404(order_id: str, db: Session, user: User) -> Order:
#     q = (db.query(Order)
#          .options(
#              joinedload(Order.customer),
#              joinedload(Order.laundry_detail),
#              joinedload(Order.fashion_detail),
#              joinedload(Order.garment_items),
#              joinedload(Order.status_history).joinedload(OrderStatusHistory.changed_by),
#              joinedload(Order.delivery_area),
#          )
#          .filter(Order.id == order_id, Order.deleted == False))  # noqa: E712
#     if user.has_role("customer"):
#         q = q.filter(or_(Order.customer_id == user.id, Order.behalf_user_id == user.id))
#     order = q.first()
#     if not order:
#         raise NotFoundError("Order", order_id)
#     return order


# # ─── LAUNDRY ─────────────────────────────────────────────────────────────────

# @router.post("", status_code=201)
# def create_laundry_order(
#     payload: LaundryOrderCreate,
#     background: BackgroundTasks,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     customer_id = user.id
#     behalf_id = None
#     if payload.behalf_user_id and user.has_role("admin", "staff"):
#         behalf_id = payload.behalf_user_id
#         customer_id = payload.behalf_user_id

#     if payload.payment_method == PaymentMethodType.SUBSCRIPTION:
#         _validate_subscription_payment(payload, customer_id, db)

#     garment_total = sum(
#         Decimal(str(g.unit_price)) * g.quantity * Decimal(str(g.service_multiplier))
#         for g in payload.garments
#     )
#     priority_sc = garment_total * Decimal("0.5") if payload.priority == OrderPriority.EXPRESS else Decimal("0")
#     from app.models.pricing import DeliveryArea as DA
#     delivery_fee = Decimal("0")
#     if payload.delivery_area_id:
#         area = db.get(DA, payload.delivery_area_id)
#         delivery_fee = area.price if area else Decimal("0")
#     total = garment_total + priority_sc + delivery_fee

#     ref = generate_order_reference("LD")
#     order = Order(
#         reference=ref,
#         order_type=OrderType.LAUNDRY,
#         customer_id=customer_id,
#         behalf_user_id=behalf_id,
#         created_by_id=user.id,
#         pickup_date=payload.pickup_date,
#         pickup_time=payload.pickup_time,
#         delivery_area_id=payload.delivery_area_id,
#         delivery_address=payload.delivery_address,
#         priority=payload.priority,
#         payment_method=payload.payment_method,
#         payment_status="pending",
#         customer_subscription_id=payload.subscription_id,
#         special_instructions=payload.special_instructions,
#         garment_subtotal=garment_total,
#         priority_surcharge=priority_sc,
#         delivery_fee=delivery_fee,
#         total_amount=total,
#         status=LaundryStatus.RECEIVED.value,
#     )
#     db.add(order)
#     db.flush()

#     ld = LaundryOrder(
#         id=order.id,
#         laundry_status=LaundryStatus.RECEIVED,
#         garment_count=sum(g.quantity for g in payload.garments),
#         services_json=[s.model_dump() for s in payload.services],
#         is_express=payload.priority == OrderPriority.EXPRESS,
#     )
#     db.add(ld)

#     for g in payload.garments:
#         db.add(OrderGarmentItem(
#             order_id=order.id,
#             garment_type_id=g.garment_type_id,
#             garment_name=g.garment_name,
#             category=g.category,
#             quantity=g.quantity,
#             unit_price=g.unit_price,
#             service_multiplier=g.service_multiplier,
#             line_total=Decimal(str(g.unit_price)) * g.quantity * Decimal(str(g.service_multiplier)),
#         ))

#     db.add(OrderStatusHistory(
#         order_id=order.id, from_status=None,
#         to_status=LaundryStatus.RECEIVED.value,
#         changed_by_id=user.id, notes="Order created",
#     ))
#     db.flush()

#     if payload.payment_method == PaymentMethodType.SUBSCRIPTION:
#         _deduct_subscription_units(payload, customer_id, order.id, user.id, db)
#         order.payment_status = "paid"

#     customer = db.get(User, customer_id)
#     if customer:
#         background.add_task(
#             send_order_confirmed, customer.email, customer.names,
#             ref, "laundry", f"₦{total:,.0f}"
#         )
#         background.add_task(notify_order_status, db, customer_id, ref, LaundryStatus.RECEIVED.value)

#     db.flush()
#     return api_response(
#         True, "Order created.",
#         data={"id": order.id, "reference": ref, "total_amount": float(total)},
#         status_code=201,
#     )


# def _validate_subscription_payment(payload, customer_id, db: Session):
#     if payload.sub_allocations:
#         total_alloc = sum(a.units for a in payload.sub_allocations)
#         if total_alloc < sum(g.quantity for g in payload.garments):
#             raise CustomAPIException("Allocated units insufficient for garment count.", 400)
#     elif payload.customer_subscription_id:
#         sub = db.query(CustomerSubscription).filter(
#             CustomerSubscription.id == payload.customer_subscription_id,
#             CustomerSubscription.user_id == customer_id,
#             CustomerSubscription.status == SubscriptionStatus.ACTIVE,
#         ).first()
#         if not sub:
#             raise CustomAPIException("Active subscription not found.", 400, "NO_ACTIVE_SUB")
#         required = sum(g.quantity for g in payload.garments)
#         if sub.units_remaining < required:
#             from app.core.exceptions.custom_exceptions import InsufficientUnitsError
#             raise InsufficientUnitsError(required, sub.units_remaining)


# def _deduct_subscription_units(payload, customer_id, order_id: str, staff_id, db: Session):
#     from app.models.platform_billing import CustomerUsageLog
#     from app.enums.stitch import UsagePaymentSource
#     from sqlalchemy.orm import joinedload as jl
#     total_garments = sum(g.quantity for g in payload.garments)

#     if payload.sub_allocations:
#         for alloc in payload.sub_allocations:
#             sub = db.query(CustomerSubscription).options(jl(CustomerSubscription.plan)).filter(
#                 CustomerSubscription.id == alloc.subscription_id, CustomerSubscription.user_id == customer_id
#             ).first()
#             if sub:
#                 before = sub.units_remaining
#                 sub.units_used += alloc.units
#                 db.add(CustomerUsageLog(
#                     user_id=customer_id, subscription_id=sub.id, order_id=order_id,
#                     recorded_by_id=staff_id, units_deducted=alloc.units,
#                     source=UsagePaymentSource.SUBSCRIPTION,
#                     plan_name=sub.plan.name if sub.plan else None,
#                     description="Order payment deduction",
#                     balance_before=before, balance_after=sub.units_remaining,
#                     total_units_snapshot=sub.units,
#                 ))
#     elif payload.customer_subscription_id:
#         sub = db.query(CustomerSubscription).options(jl(CustomerSubscription.plan)).filter(
#             CustomerSubscription.id == payload.customer_subscription_id, CustomerSubscription.user_id == customer_id
#         ).first()
#         if sub:
#             before = sub.units_remaining
#             sub.units_used += total_garments
#             db.add(CustomerUsageLog(
#                 user_id=customer_id, subscription_id=sub.id, order_id=order_id,
#                 recorded_by_id=staff_id, units_deducted=total_garments,
#                 source=UsagePaymentSource.SUBSCRIPTION,
#                 plan_name=sub.plan.name if sub.plan else None,
#                 description="Order payment deduction",
#                 balance_before=before, balance_after=sub.units_remaining,
#                 total_units_snapshot=sub.units,
#             ))


# @router.get("")
# def list_orders(
#     page: int = Query(1, ge=1),
#     page_size: int = Query(20, ge=1, le=100),
#     order_type: Optional[OrderType] = None,
#     status: Optional[str] = None,
#     priority: Optional[OrderPriority] = None,
#     search: Optional[str] = None,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     q = (db.query(Order)
#          .options(
#              joinedload(Order.customer), joinedload(Order.laundry_detail),
#              joinedload(Order.fashion_detail), joinedload(Order.delivery_area),
#          )
#          .filter(Order.deleted == False))  # noqa: E712
#     if user.has_role("customer"):
#         q = q.filter(or_(Order.customer_id == user.id, Order.behalf_user_id == user.id))
#     if order_type:
#         q = q.filter(Order.order_type == order_type)
#     if status:
#         q = q.filter(Order.status == status)
#     if priority:
#         q = q.filter(Order.priority == priority)
#     if search:
#         term = f"%{search}%"
#         q = q.join(Order.customer).filter(or_(
#             Order.reference.ilike(term), User.names.ilike(term), User.phone.ilike(term)
#         ))
#     total = q.count()
#     orders = q.order_by(desc(Order.created_at)).offset((page - 1) * page_size).limit(page_size).all()
#     items = [_enrich_laundry(o) if o.order_type == OrderType.LAUNDRY else _enrich_fashion(o) for o in orders]
#     total_pages = (total + page_size - 1) // page_size if page_size else 0
#     return api_response(True, "Orders fetched.", data={
#         "items": items,
#         "pagination": {
#             "page": page, "page_size": page_size, "total": total,
#             "total_pages": total_pages, "has_next": page < total_pages, "has_prev": page > 1,
#         },
#     })


# @router.get("/{order_id}")
# def get_order(order_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
#     order = _get_order_or_404(order_id, db, user)
#     enriched = _enrich_laundry(order) if order.order_type == OrderType.LAUNDRY else _enrich_fashion(order)
#     return api_response(True, "Order fetched.", data=enriched)


# @router.put("/{order_id}/status")
# def update_order_status(
#     order_id: str,
#     payload: OrderStatusUpdate,
#     background: BackgroundTasks,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     if user.has_role("customer"):
#         raise ForbiddenError("Customers cannot update order status.")
#     order = _get_order_or_404(order_id, db, user)
#     prev = order.status
#     order.status = payload.status
#     if order.order_type == OrderType.LAUNDRY and order.laundry_detail:
#         try:
#             order.laundry_detail.laundry_status = LaundryStatus(payload.status)
#         except ValueError:
#             pass
#     elif order.order_type == OrderType.FASHION and order.fashion_detail:
#         try:
#             order.fashion_detail.fashion_status = FashionStatus(payload.status)
#         except ValueError:
#             pass
#     db.add(OrderStatusHistory(
#         order_id=order.id, from_status=prev,
#         to_status=payload.status, changed_by_id=user.id,
#         notes=payload.notes, is_reversal=payload.is_reversal,
#     ))
#     background.add_task(notify_order_status, db, order.customer_id, order.reference, payload.status)
#     background.add_task(
#         send_order_status_update,
#         order.customer.email if order.customer else "",
#         order.customer.names if order.customer else "",
#         order.reference, payload.status,
#     )
#     enriched = _enrich_laundry(order) if order.order_type == OrderType.LAUNDRY else _enrich_fashion(order)
#     return api_response(True, "Order status updated.", data=enriched)


# @router.put("/{order_id}", dependencies=[Depends(require_roles("admin", "staff", "super_admin"))])
# def update_order(
#     order_id: str,
#     payload: LaundryOrderUpdate,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     order = _get_order_or_404(order_id, db, user)
#     for k, v in payload.model_dump(exclude_none=True).items():
#         if hasattr(order, k):
#             setattr(order, k, v)
#     return api_response(True, "Order updated.")


# # ─── FASHION ─────────────────────────────────────────────────────────────────

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
#         payment_status="pending",
#         total_amount=payload.total_amount,
#         status=FashionStatus.CONSULTATION.value,
#     )
#     db.add(order)
#     db.flush()

#     db.add(FashionOrder(
#         id=order.id,
#         fashion_status=FashionStatus.CONSULTATION,
#         service_type=payload.service_type,
#         item_name=payload.item_name,
#         fabric_source=payload.fabric_source,
#         measurements=payload.measurements.model_dump() if payload.measurements else None,
#         design_notes=payload.design_notes,
#         reference_images=payload.reference_images,
#         consultation_date=payload.consultation_date,
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

#     return api_response(True, "Fashion order created.", data={"id": order.id, "reference": ref}, status_code=201)


# @router.put("/fashion-orders/{order_id}", dependencies=[Depends(require_roles("admin", "staff", "super_admin"))])
# def update_fashion_order(
#     order_id: str,
#     payload: FashionOrderUpdate,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     order = _get_order_or_404(order_id, db, user)
#     if order.order_type != OrderType.FASHION:
#         raise CustomAPIException("Not a fashion order.", 400)
#     fd = order.fashion_detail
#     if fd:
#         for k, v in payload.model_dump(exclude_none=True).items():
#             if k == "measurements" and v:
#                 fd.measurements = v.model_dump() if hasattr(v, "model_dump") else v
#             elif hasattr(fd, k):
#                 setattr(fd, k, v)
#     if payload.internal_notes:
#         order.internal_notes = payload.internal_notes
#     if payload.delivery_address:
#         order.delivery_address = payload.delivery_address
#     return api_response(True, "Fashion order updated.")



# v2
"""app/api/v1/orders.py — Laundry and Fashion order endpoints."""
import logging
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session, joinedload

from app.api.deps.users import get_current_user, get_db
from app.api.deps.rbac import require_roles
from app.core.exceptions.custom_exceptions import CustomAPIException, ForbiddenError, NotFoundError
from app.enums.stitch import (
    LaundryStatus, FashionStatus, OrderPriority, OrderType,
    PaymentMethodType,
)
from app.enums.billing import SubscriptionStatus

from app.models.orders import (
    FashionOrder, LaundryOrder, Order, OrderGarmentItem, OrderStatusHistory,
)

from app.models.tenant_billing import ServicePlan, CustomerSubscription
from app.models.users import User
from app.schemas.orders import (
    FashionOrderCreate, FashionOrderOut, FashionOrderUpdate,
    LaundryOrderCreate, LaundryOrderOut, LaundryOrderUpdate,
    OrderStatusUpdate, StatusHistoryOut, GarmentItemOut,
)
from app.services.email_service import send_order_confirmed, send_order_status_update
from app.services.notification_service import notify_order_status
from app.utils.helpers import generate_order_reference
from app.utils.responses import api_response

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Orders"])


def _enrich_laundry(order: Order) -> LaundryOrderOut:
    return LaundryOrderOut(
        id=order.id, reference=order.reference,
        customer_id=order.customer_id,
        customer_name=order.customer.names if order.customer else None,
        customer_phone=order.customer.phone if order.customer else None,
        status=order.status,
        laundry_status=order.laundry_detail.laundry_status if order.laundry_detail else None,
        priority=order.priority,
        payment_method=order.payment_method,
        payment_status=order.payment_status,
        pickup_date=order.pickup_date,
        pickup_time=order.pickup_time,
        delivery_area=order.delivery_area.name if order.delivery_area else None,
        delivery_address=order.delivery_address,
        garment_subtotal=order.garment_subtotal,
        priority_surcharge=order.priority_surcharge,
        delivery_fee=order.delivery_fee,
        total_amount=order.total_amount,
        garment_count=order.laundry_detail.garment_count if order.laundry_detail else None,
        garment_items=[GarmentItemOut.model_validate(g) for g in order.garment_items],
        status_history=[
            StatusHistoryOut(
                id=h.id, from_status=h.from_status, to_status=h.to_status,
                notes=h.notes, is_reversal=h.is_reversal, created_at=h.created_at,
                changed_by_name=h.changed_by.names if h.changed_by else None,
            ) for h in order.status_history
        ],
        services_json=order.laundry_detail.services_json if order.laundry_detail else None,
        special_instructions=order.special_instructions,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def _enrich_fashion(order: Order) -> FashionOrderOut:
    fd = order.fashion_detail
    return FashionOrderOut(
        id=order.id, reference=order.reference,
        customer_id=order.customer_id,
        customer_name=order.customer.names if order.customer else None,
        customer_phone=order.customer.phone if order.customer else None,
        status=order.status,
        fashion_status=fd.fashion_status if fd else None,
        service_type=fd.service_type if fd else None,
        item_name=fd.item_name if fd else None,
        fabric_source=fd.fabric_source if fd else None,
        measurements=fd.measurements if fd else None,
        design_notes=fd.design_notes if fd else None,
        reference_images=fd.reference_images if fd else None,
        priority=order.priority,
        payment_method=order.payment_method,
        payment_status=order.payment_status,
        total_amount=order.total_amount,
        consultation_date=fd.consultation_date if fd else None,
        fitting_date=fd.fitting_date if fd else None,
        delivery_address=order.delivery_address,
        status_history=[
            StatusHistoryOut(
                id=h.id, from_status=h.from_status, to_status=h.to_status,
                notes=h.notes, is_reversal=h.is_reversal, created_at=h.created_at,
                changed_by_name=h.changed_by.names if h.changed_by else None,
            ) for h in order.status_history
        ],
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def _get_order_or_404(order_id: str, db: Session, user: User) -> Order:
    q = (db.query(Order)
         .options(
             joinedload(Order.customer),
             joinedload(Order.laundry_detail),
             joinedload(Order.fashion_detail),
             joinedload(Order.garment_items),
             joinedload(Order.status_history).joinedload(OrderStatusHistory.changed_by),
             joinedload(Order.delivery_area),
         )
         .filter(Order.id == order_id, Order.deleted == False))  # noqa: E712
    if user.has_role("customer"):
        q = q.filter(or_(Order.customer_id == user.id, Order.behalf_user_id == user.id))
    order = q.first()
    if not order:
        raise NotFoundError("Order", order_id)
    return order


# ─── LAUNDRY ─────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
def create_laundry_order(
    payload: LaundryOrderCreate,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    customer_id = user.id
    behalf_id = None
    if payload.behalf_user_id and user.has_role("admin", "staff"):
        behalf_id = payload.behalf_user_id
        customer_id = payload.behalf_user_id

    if payload.payment_method == PaymentMethodType.SUBSCRIPTION:
        _validate_subscription_payment(payload, customer_id, db)

    # ── Server-side price calculation (ignore client totals to prevent tampering)
    garment_total = sum(
        Decimal(str(g.unit_price)) * g.quantity * Decimal(str(g.service_multiplier))
        for g in payload.garments
    )
    priority_sc = garment_total * Decimal("0.5") if payload.priority == OrderPriority.EXPRESS else Decimal("0")
    from app.models.pricing import DeliveryArea as DA
    delivery_fee = Decimal("0")
    if payload.delivery_area_id:
        area = db.get(DA, payload.delivery_area_id)
        delivery_fee = area.price if area else Decimal("0")
    total = garment_total + priority_sc + delivery_fee

    # Optional: verify client-submitted totals match (catches front-end bugs / manipulation)
    if payload.total_amount and abs(Decimal(str(payload.total_amount)) - total) > Decimal("0.01"):
        raise CustomAPIException("Order total mismatch. Please refresh and try again.", 400)

    ref = generate_order_reference("LD")

    # If the front-end already verified a direct Paystack payment inline, record it
    is_paid_inline = bool(payload.payment_reference) and payload.payment_method == PaymentMethodType.DIRECT

    order = Order(
        reference=ref,
        order_type=OrderType.LAUNDRY,
        customer_id=customer_id,
        behalf_user_id=behalf_id,
        created_by_id=user.id,
        pickup_date=payload.pickup_date,
        pickup_time=payload.pickup_time,
        delivery_area_id=payload.delivery_area_id,
        delivery_address=payload.delivery_address,
        priority=payload.priority,
        payment_method=payload.payment_method,
        payment_status="paid" if is_paid_inline else "pending",
        payment_reference=payload.payment_reference,
        customer_subscription_id=payload.subscription_id,
        special_instructions=payload.special_instructions,
        garment_subtotal=garment_total,
        priority_surcharge=priority_sc,
        delivery_fee=delivery_fee,
        total_amount=total,
        status=LaundryStatus.RECEIVED.value,
    )
    db.add(order)
    db.flush()

    # FIX: order_id was missing — this caused the IntegrityError
    ld = LaundryOrder(
        id=order.id,                     # keep only if your base model requires it
        order_id=order.id,               # <-- REQUIRED FK to parent orders table
        laundry_status=LaundryStatus.RECEIVED,
        garment_count=sum(g.quantity for g in payload.garments),
        services_json=[s.model_dump() for s in payload.services],
        is_express=payload.priority == OrderPriority.EXPRESS,
    )
    db.add(ld)

    for g in payload.garments:
        db.add(OrderGarmentItem(
            order_id=order.id,
            garment_type_id=g.garment_type_id,
            garment_name=g.garment_name,
            category=g.category,
            quantity=g.quantity,
            unit_price=g.unit_price,
            service_multiplier=g.service_multiplier,
            line_total=Decimal(str(g.unit_price)) * g.quantity * Decimal(str(g.service_multiplier)),
        ))

    db.add(OrderStatusHistory(
        order_id=order.id, from_status=None,
        to_status=LaundryStatus.RECEIVED.value,
        changed_by_id=user.id, notes="Order created",
    ))
    db.flush()

    if payload.payment_method == PaymentMethodType.SUBSCRIPTION:
        _deduct_subscription_units(payload, customer_id, order.id, user.id, db)
        order.payment_status = "paid"

    customer = db.get(User, customer_id)
    if customer:
        background.add_task(
            send_order_confirmed, customer.email, customer.names,
            ref, "laundry", f"₦{total:,.0f}"
        )
        background.add_task(notify_order_status, db, customer_id, ref, LaundryStatus.RECEIVED.value)

    db.flush()
    return api_response(
        True, "Order created.",
        data={"id": order.id, "reference": ref, "total_amount": float(total)},
        status_code=201,
    )


def _validate_subscription_payment(payload, customer_id, db: Session):
    if payload.sub_allocations:
        total_garments = sum(g.quantity for g in payload.garments)
        total_alloc = sum(a.units for a in payload.sub_allocations)
        if total_alloc != total_garments:
            raise CustomAPIException(
                f"Allocated units ({total_alloc}) must exactly equal garment count ({total_garments}).", 400
            )
        for alloc in payload.sub_allocations:
            sub = db.query(CustomerSubscription).filter(
                CustomerSubscription.id == alloc.subscription_id,
                CustomerSubscription.user_id == customer_id,
                CustomerSubscription.status == SubscriptionStatus.ACTIVE,
            ).first()
            if not sub:
                raise CustomAPIException(f"Active subscription {alloc.subscription_id} not found.", 400, "NO_ACTIVE_SUB")
            if sub.units_remaining < alloc.units:
                from app.core.exceptions.custom_exceptions import InsufficientUnitsError
                raise InsufficientUnitsError(alloc.units, sub.units_remaining)
    elif payload.customer_subscription_id:
        sub = db.query(CustomerSubscription).filter(
            CustomerSubscription.id == payload.customer_subscription_id,
            CustomerSubscription.user_id == customer_id,
            CustomerSubscription.status == SubscriptionStatus.ACTIVE,
        ).first()
        if not sub:
            raise CustomAPIException("Active subscription not found.", 400, "NO_ACTIVE_SUB")
        required = sum(g.quantity for g in payload.garments)
        if sub.units_remaining < required:
            from app.core.exceptions.custom_exceptions import InsufficientUnitsError
            raise InsufficientUnitsError(required, sub.units_remaining)


def _deduct_subscription_units(payload, customer_id, order_id: str, staff_id, db: Session):
    from app.models.platform_billing import CustomerUsageLog
    from app.enums.stitch import UsagePaymentSource
    from sqlalchemy.orm import joinedload as jl
    total_garments = sum(g.quantity for g in payload.garments)

    if payload.sub_allocations:
        for alloc in payload.sub_allocations:
            sub = db.query(CustomerSubscription).options(jl(CustomerSubscription.plan)).filter(
                CustomerSubscription.id == alloc.subscription_id, CustomerSubscription.user_id == customer_id
            ).first()
            if sub:
                before = sub.units_remaining
                sub.units_used += alloc.units
                # If units_remaining is a stored column (not a hybrid property), also decrement it:
                # sub.units_remaining -= alloc.units
                db.add(CustomerUsageLog(
                    user_id=customer_id, subscription_id=sub.id, order_id=order_id,
                    recorded_by_id=staff_id, units_deducted=alloc.units,
                    source=UsagePaymentSource.SUBSCRIPTION,
                    plan_name=sub.plan.name if sub.plan else None,
                    description="Order payment deduction",
                    balance_before=before, balance_after=sub.units_remaining,
                    total_units_snapshot=sub.units,
                ))
    elif payload.customer_subscription_id:
        sub = db.query(CustomerSubscription).options(jl(CustomerSubscription.plan)).filter(
            CustomerSubscription.id == payload.customer_subscription_id, CustomerSubscription.user_id == customer_id
        ).first()
        if sub:
            before = sub.units_remaining
            sub.units_used += total_garments
            # sub.units_remaining -= total_garments
            db.add(CustomerUsageLog(
                user_id=customer_id, subscription_id=sub.id, order_id=order_id,
                recorded_by_id=staff_id, units_deducted=total_garments,
                source=UsagePaymentSource.SUBSCRIPTION,
                plan_name=sub.plan.name if sub.plan else None,
                description="Order payment deduction",
                balance_before=before, balance_after=sub.units_remaining,
                total_units_snapshot=sub.units,
            ))


@router.get("")
def list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    order_type: Optional[OrderType] = None,
    status: Optional[str] = None,
    priority: Optional[OrderPriority] = None,
    search: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = (db.query(Order)
         .options(
             joinedload(Order.customer), joinedload(Order.laundry_detail),
             joinedload(Order.fashion_detail), joinedload(Order.delivery_area),
         )
         .filter(Order.deleted == False))  # noqa: E712
    if user.has_role("customer"):
        q = q.filter(or_(Order.customer_id == user.id, Order.behalf_user_id == user.id))
    if order_type:
        q = q.filter(Order.order_type == order_type)
    if status:
        q = q.filter(Order.status == status)
    if priority:
        q = q.filter(Order.priority == priority)
    if search:
        term = f"%{search}%"
        q = q.join(Order.customer).filter(or_(
            Order.reference.ilike(term), User.names.ilike(term), User.phone.ilike(term)
        ))
    total = q.count()
    orders = q.order_by(desc(Order.created_at)).offset((page - 1) * page_size).limit(page_size).all()
    items = [_enrich_laundry(o) if o.order_type == OrderType.LAUNDRY else _enrich_fashion(o) for o in orders]
    total_pages = (total + page_size - 1) // page_size if page_size else 0
    return api_response(True, "Orders fetched.", data={
        "items": items,
        "pagination": {
            "page": page, "page_size": page_size, "total": total,
            "total_pages": total_pages, "has_next": page < total_pages, "has_prev": page > 1,
        },
    })


@router.get("/{order_id}")
def get_order(order_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = _get_order_or_404(order_id, db, user)
    enriched = _enrich_laundry(order) if order.order_type == OrderType.LAUNDRY else _enrich_fashion(order)
    return api_response(True, "Order fetched.", data=enriched)


@router.put("/{order_id}/status")
def update_order_status(
    order_id: str,
    payload: OrderStatusUpdate,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.has_role("customer"):
        raise ForbiddenError("Customers cannot update order status.")
    order = _get_order_or_404(order_id, db, user)
    prev = order.status
    order.status = payload.status
    if order.order_type == OrderType.LAUNDRY and order.laundry_detail:
        try:
            order.laundry_detail.laundry_status = LaundryStatus(payload.status)
        except ValueError:
            pass
    elif order.order_type == OrderType.FASHION and order.fashion_detail:
        try:
            order.fashion_detail.fashion_status = FashionStatus(payload.status)
        except ValueError:
            pass
    db.add(OrderStatusHistory(
        order_id=order.id, from_status=prev,
        to_status=payload.status, changed_by_id=user.id,
        notes=payload.notes, is_reversal=payload.is_reversal,
    ))
    background.add_task(notify_order_status, db, order.customer_id, order.reference, payload.status)
    background.add_task(
        send_order_status_update,
        order.customer.email if order.customer else "",
        order.customer.names if order.customer else "",
        order.reference, payload.status,
    )
    enriched = _enrich_laundry(order) if order.order_type == OrderType.LAUNDRY else _enrich_fashion(order)
    return api_response(True, "Order status updated.", data=enriched)


@router.put("/{order_id}", dependencies=[Depends(require_roles("admin", "staff", "super_admin"))])
def update_order(
    order_id: str,
    payload: LaundryOrderUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = _get_order_or_404(order_id, db, user)
    for k, v in payload.model_dump(exclude_none=True).items():
        if hasattr(order, k):
            setattr(order, k, v)
    return api_response(True, "Order updated.")


# ─── FASHION ─────────────────────────────────────────────────────────────────

@router.post("/fashion-orders", status_code=201)
def create_fashion_order(
    payload: FashionOrderCreate,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    customer_id = user.id
    behalf_id = None
    if payload.behalf_user_id and user.has_role("admin", "staff"):
        behalf_id = payload.behalf_user_id
        customer_id = payload.behalf_user_id

    ref = generate_order_reference("FS")
    order = Order(
        reference=ref,
        order_type=OrderType.FASHION,
        customer_id=customer_id,
        behalf_user_id=behalf_id,
        created_by_id=user.id,
        delivery_address=payload.delivery_address,
        priority=payload.priority,
        payment_method=payload.payment_method,
        payment_status="pending",
        total_amount=payload.total_amount,
        status=FashionStatus.CONSULTATION.value,
    )
    db.add(order)
    db.flush()

    # FIX: added order_id=order.id (same pattern as laundry)
    db.add(FashionOrder(
        id=order.id,
        order_id=order.id,
        fashion_status=FashionStatus.CONSULTATION,
        service_type=payload.service_type,
        item_name=payload.item_name,
        fabric_source=payload.fabric_source,
        measurements=payload.measurements.model_dump() if payload.measurements else None,
        design_notes=payload.design_notes,
        reference_images=payload.reference_images,
        consultation_date=payload.consultation_date,
    ))
    db.add(OrderStatusHistory(
        order_id=order.id, from_status=None,
        to_status=FashionStatus.CONSULTATION.value,
        changed_by_id=user.id, notes="Fashion order created",
    ))
    db.flush()

    customer = db.get(User, customer_id)
    if customer:
        background.add_task(notify_order_status, db, customer_id, ref, FashionStatus.CONSULTATION.value)

    return api_response(True, "Fashion order created.", data={"id": order.id, "reference": ref}, status_code=201)


@router.put("/fashion-orders/{order_id}", dependencies=[Depends(require_roles("admin", "staff", "super_admin"))])
def update_fashion_order(
    order_id: str,
    payload: FashionOrderUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = _get_order_or_404(order_id, db, user)
    if order.order_type != OrderType.FASHION:
        raise CustomAPIException("Not a fashion order.", 400)
    fd = order.fashion_detail
    if fd:
        for k, v in payload.model_dump(exclude_none=True).items():
            if k == "measurements" and v:
                fd.measurements = v.model_dump() if hasattr(v, "model_dump") else v
            elif hasattr(fd, k):
                setattr(fd, k, v)
    if payload.internal_notes:
        order.internal_notes = payload.internal_notes
    if payload.delivery_address:
        order.delivery_address = payload.delivery_address
    return api_response(True, "Fashion order updated.")

