"""app/api/root_router.py — Health, version, and root routes."""
from datetime import datetime, timezone
from fastapi import APIRouter
from app.core.config import get_app_config
from app.db.database import db_ping
from app.services.redis_service import get_redis

root_router = APIRouter()


@root_router.get("/", tags=["Root"])
def root():
    cfg = get_app_config()
    return {
        "name": cfg.general_config.site_name,
        "description": cfg.general_config.site_description,
        "version": cfg.general_config.api_version,
        "docs": "/docs" if cfg.general_config.development_mode else None,
        "status": "ok",
    }


@root_router.get("/health", tags=["Health"])
def health_check():
    cfg = get_app_config()
    db_status = db_ping()

    redis_status = "ok"
    try:
        r = get_redis()
        r.ping()
    except Exception as exc:
        redis_status = f"error: {exc}"

    overall = "ok" if db_status == "ok" and redis_status == "ok" else "degraded"
    return {
        "status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": "development" if cfg.general_config.development_mode else "production",
        "services": {
            "database": db_status,
            "redis":    redis_status,
        },
    }


@root_router.get("/ping", tags=["Health"])
def ping():
    return {"pong": True, "ts": datetime.now(timezone.utc).isoformat()}

