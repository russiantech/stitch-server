"""app/schemas/notifications.py — Notification output schema."""
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID
from pydantic import BaseModel
from app.enums.stitch import NotificationType


class NotificationOut(BaseModel):
    id: UUID
    title: str
    message: str
    type: NotificationType
    is_read: bool
    read_at: Optional[datetime]
    action_url: Optional[str]
    meta: Optional[Dict[str, Any]]
    created_at: datetime

    model_config = {"from_attributes": True}

