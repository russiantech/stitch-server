"""app/api/v1/analytics.py — Dashboard KPIs and reporting."""
from asyncio.log import logger
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.api.deps.auth import require_staff_or_admin
from app.db.database import get_db
from app.enums.stitch import OrderType, PaymentStatus 
from app.enums.billing import SubscriptionStatus
from app.models.orders import Order
from app.models.payments.base import Payment
from app.models.tenant_billing import CustomerSubscription
from app.models.users import User
from app.models.rbac import Role
from app.utils.responses import api_response

router = APIRouter(tags=["Analytics"])


@router.get("/dashboard")
def dashboard_kpis(
    period: str = Query("month", pattern="^(week|month|quarter|year)$"),
    staff: User = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
):  
    try:
        now = datetime.now(timezone.utc)
        periods = {
            "week":    timedelta(weeks=1),
            "month":   timedelta(days=30),
            "quarter": timedelta(days=91),
            "year":    timedelta(days=365),
        }
        since      = now - periods.get(period, timedelta(days=30))
        prev_since = since - periods.get(period, timedelta(days=30))

        # Revenue
        def _rev(from_dt, to_dt):
            r = db.query(func.sum(Payment.amount_paid)).filter(
                Payment.status == PaymentStatus.SUCCESS,
                Payment.paid_at.between(from_dt, to_dt),
            ).scalar()
            return float(r or 0)

        rev_cur  = _rev(since, now)
        rev_prev = _rev(prev_since, since)
        rev_growth = round(((rev_cur - rev_prev) / rev_prev * 100), 1) if rev_prev else 0.0

        # Orders
        total_orders     = db.query(func.count(Order.id)).filter(Order.deleted == False).scalar()
        orders_this_per  = db.query(func.count(Order.id)).filter(Order.created_at >= since, Order.deleted == False).scalar()
        laundry_orders   = db.query(func.count(Order.id)).filter(Order.order_type == OrderType.LAUNDRY, Order.deleted == False).scalar()
        fashion_orders   = db.query(func.count(Order.id)).filter(Order.order_type == OrderType.FASHION, Order.deleted == False).scalar()
        pending_orders   = db.query(func.count(Order.id)).filter(
            Order.status.notin_(["Completed", "Cancelled", "Delivered"]),
            Order.deleted == False,
        ).scalar()

        # Customers
        total_customers  = db.query(func.count(User.id)).join(User.roles).filter(
            Role.name == "customer", User.deleted == False
        ).scalar()
        new_customers    = db.query(func.count(User.id)).join(User.roles).filter(
            Role.name == "customer", User.created_at >= since, User.deleted == False
        ).scalar()

        # Deliveries
        delivered        = db.query(func.count(Order.id)).filter(Order.status == "Delivered", Order.deleted == False).scalar()
        completed        = db.query(func.count(Order.id)).filter(Order.status == "Completed", Order.deleted == False).scalar()

        # Status breakdown
        status_rows = db.query(Order.status, func.count(Order.id)).filter(
            Order.deleted == False
        ).group_by(Order.status).all()
        status_breakdown = {row.status: row[1] for row in status_rows}

        return api_response(
            success=True,
            message="Dashboard KPIs fetched.",
            data={
                "revenue": {
                    "total":       _rev(datetime(2020, 1, 1, tzinfo=timezone.utc), now),
                    "this_period": rev_cur,
                    "prev_period": rev_prev,
                    "growth":      rev_growth,
                    "currency":    "NGN",
                },
                "orders": {
                    "total":       total_orders,
                    "this_period": orders_this_per,
                    "laundry":     laundry_orders,
                    "fashion":     fashion_orders,
                    "pending":     pending_orders,
                },
                "customers": {
                    "total":       total_customers,
                    "new_period":  new_customers,
                },
                "deliveries": {
                    "delivered":   delivered,
                    "completed":   completed,
                },
                "status_breakdown": status_breakdown,
                "period": period,
            },
        )
    
    except Exception as e:
        logger.error(f"Error fetching dashboard KPIs: {str(e)}", exc_info=True)
        return api_response(success=False, message=f"Error fetching dashboard KPIs: {str(e)}", data=None, status_code=500)

@router.get("/revenue")
def revenue_chart(
    months: int = Query(6, ge=1, le=24),
    staff: User = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
):
    now   = datetime.now(timezone.utc)
    data  = []
    for i in range(months - 1, -1, -1):
        start = (now - timedelta(days=30 * i)).replace(day=1, hour=0, minute=0, second=0)
        end   = (start + timedelta(days=32)).replace(day=1)
        rev   = db.query(func.sum(Payment.amount_paid)).filter(
            Payment.status == PaymentStatus.SUCCESS,
            Payment.paid_at.between(start, end),
        ).scalar() or 0
        orders = db.query(func.count(Order.id)).filter(
            Order.created_at.between(start, end), Order.deleted == False
        ).scalar() or 0
        data.append({
            "month":  start.strftime("%b"),
            "year":   start.year,
            "label":  start.strftime("%b %Y"),
            "revenue": float(rev),
            "orders":  orders,
        })
    return api_response(
        success=True,
        message="Revenue chart data.",
        data={"chart": data},
    )


@router.get("/subscriptions")
def subscription_analytics(
    staff: User = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
):
    active    = db.query(func.count(CustomerSubscription.id)).filter(CustomerSubscription.status == SubscriptionStatus.ACTIVE).scalar()
    paused    = db.query(func.count(CustomerSubscription.id)).filter(CustomerSubscription.status == SubscriptionStatus.PAUSED).scalar()
    cancelled = db.query(func.count(CustomerSubscription.id)).filter(CustomerSubscription.status == SubscriptionStatus.CANCELED).scalar()
    total_rev = db.query(func.sum(Payment.amount_paid)).filter(
        Payment.status == PaymentStatus.SUCCESS,
        Payment.purpose == "subscription",
    ).scalar() or 0
    return api_response(
        success=True,
        message="Subscription analytics.",
        data={
            "active":    active,
            "paused":    paused,
            "cancelled": cancelled,
            "total_subscription_revenue": float(total_rev),
        },
    )