"""app/api/v1/notifications.py — In-app notifications."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user
from app.db.database import get_db
from app.models.notifications import Notification
from app.models.users import User
from app.schemas.notifications import NotificationOut
from app.utils.responses import api_response
from datetime import datetime, timezone

router = APIRouter(tags=["Notifications"])


@router.get("")
def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    unread_only: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        q = q.filter(Notification.is_read == False)
    total = q.count()
    items = q.order_by(desc(Notification.created_at)).offset((page-1)*page_size).limit(page_size).all()
    return api_response(
        success=True,
        message="Notifications fetched.",
        data={
            "items": [NotificationOut.model_validate(n) for n in items],
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


@router.get("/unread-count")
def unread_count(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    count = db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).count()
    return api_response(
        success=True,
        message="Unread count.",
        data={"count": count},
    )


@router.put("/{notif_id}/read")
def mark_read(notif_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.query(Notification).filter(Notification.id == notif_id, Notification.user_id == user.id).first()
    if n and not n.is_read:
        n.is_read = True
        n.read_at = datetime.now(timezone.utc)
    return api_response(
        success=True,
        message="Marked as read.",
        data=None,
    )


@router.put("/read-all")
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read == False
    ).update({"is_read": True, "read_at": now})
    return api_response(
        success=True,
        message="All notifications marked as read.",
        data=None,
    )
