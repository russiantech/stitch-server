# app/api/deps/storage.py
import logging
from typing import Optional

from app.core.config import get_settings
from app.services.redis_service import get_redis_service_instance, RedisService

settings = get_settings()

logger = logging.getLogger(__name__)

# ── Singleton instance, created once at module import ──
_redis_service: Optional[RedisService] = None


def get_redis_service() -> RedisService:
    
    """
    FastAPI dependency: returns singleton RedisService.
    Falls back to in-memory automatically if Redis is down.
    Never raises on connection failure.
    """
    
    global _redis_service
    
    if _redis_service is None:
        redis_url = getattr(settings, "APP_REDIS_URL", None)
        _redis_service = get_redis_service_instance(redis_url)
        logger.info(
            "RedisService initialized (fallback=%s)",
            _redis_service.using_fallback,
        )
    
    return _redis_service


def get_redis_client():
    """
    Get raw Redis client. Only use this if you NEED redis-specific features.
    Will raise if in fallback mode.
    """
    service = get_redis_service()
    return service.get_client()

