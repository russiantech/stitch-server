"""app/services/redis_service.py — Redis helper with typed get/set/delete."""
import json
import logging
from datetime import timedelta
from typing import Any, Optional
import redis as _redis
from app.core.config import get_app_config

logger = logging.getLogger(__name__)
_client: Optional[_redis.Redis] = None


def get_redis() -> _redis.Redis:
    global _client
    if _client is not None:
        return _client
    cfg = get_app_config().redis_config
    if cfg.redis_connection_string:
        _client = _redis.from_url(cfg.redis_connection_string, decode_responses=True)
    else:
        _client = _redis.Redis(
            host=cfg.host, port=cfg.port, db=cfg.db,
            password=cfg.password, decode_responses=True,
        )
    return _client


def rset(key: str, value: Any, ttl: Optional[int] = None) -> bool:
    try:
        r = get_redis()
        serialized = json.dumps(value) if not isinstance(value, str) else value
        if ttl:
            return bool(r.setex(key, timedelta(seconds=ttl), serialized))
        return bool(r.set(key, serialized))
    except Exception as e:
        logger.error("Redis SET error for key=%s: %s", key, e)
        return False


def rget(key: str) -> Optional[Any]:
    try:
        val = get_redis().get(key)
        if val is None:
            return None
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val
    except Exception as e:
        logger.error("Redis GET error for key=%s: %s", key, e)
        return None


def rdel(*keys: str) -> int:
    try:
        return get_redis().delete(*keys)
    except Exception as e:
        logger.error("Redis DEL error: %s", e)
        return 0


def rexpire(key: str, seconds: int) -> bool:
    try:
        return bool(get_redis().expire(key, seconds))
    except Exception as e:
        logger.error("Redis EXPIRE error key=%s: %s", key, e)
        return False


def rexists(key: str) -> bool:
    try:
        return bool(get_redis().exists(key))
    except Exception:
        return False


def rttl(key: str) -> int:
    try:
        return get_redis().ttl(key)
    except Exception:
        return -1


def rincr(key: str) -> int:
    """Atomic INCR. Returns new value. Sets TTL to 900s if key is new."""
    try:
        r = get_redis()
        new_val = r.incr(key)
        # Set expiry only on first creation (when value was 1)
        if new_val == 1:
            r.expire(key, 900)
        return int(new_val)
    except Exception as e:
        logger.error("Redis INCR error for key=%s: %s", key, e)
        return 1

# ── OTP helpers ───────────────────────────────────────────────────────────────

OTP_PREFIX = "stitch:otp:"
SESSION_PREFIX = "stitch:session:"
BLACKLIST_PREFIX = "stitch:blacklist:"


def store_otp(identifier: str, otp: str, ttl: int = 600) -> None:
    rset(f"{OTP_PREFIX}{identifier}", otp, ttl=ttl)


def verify_otp(identifier: str, otp: str) -> bool:
    stored = rget(f"{OTP_PREFIX}{identifier}")
    if stored and str(stored) == str(otp):
        rdel(f"{OTP_PREFIX}{identifier}")
        return True
    return False


def blacklist_token(token: str, ttl: int = 86400) -> None:
    rset(f"{BLACKLIST_PREFIX}{token}", "1", ttl=ttl)


def is_token_blacklisted(token: str) -> bool:
    return rexists(f"{BLACKLIST_PREFIX}{token}")


def store_session(session_id: str, data: dict, ttl: int = 86400) -> None:
    rset(f"{SESSION_PREFIX}{session_id}", data, ttl=ttl)


def get_session(session_id: str) -> Optional[dict]:
    return rget(f"{SESSION_PREFIX}{session_id}")


def delete_session(session_id: str) -> None:
    rdel(f"{SESSION_PREFIX}{session_id}")

