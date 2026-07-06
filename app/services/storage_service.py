"""app/services/storage_service.py — Supabase Storage integration."""
import logging
import uuid
from pathlib import Path
from typing import Optional

from supabase import create_client, Client

from app.core.config import get_app_config

logger = logging.getLogger(__name__)

_client: Optional[Client] = None
_bucket_checked = False


def get_supabase() -> Client:
    global _client
    if _client is None:
        cfg = get_app_config().storage_config.supabase
        _client = create_client(cfg.url, cfg.service_role_key)
    return _client


def ensure_bucket_exists() -> None:
    """Creates the configured bucket if it doesn't already exist.
    Safe to call multiple times — checks first, no-ops if present.
    Intended to be run once per environment via scripts/setup_supabase.py,
    not on every app startup (see notes from earlier discussion)."""
    global _bucket_checked
    if _bucket_checked:
        return

    cfg = get_app_config().storage_config.supabase
    client = get_supabase()

    try:
        existing = client.storage.list_buckets()
        names = {b.name if hasattr(b, "name") else b["name"] for b in existing}
    except Exception as exc:
        logger.error("Could not list Supabase buckets: %s", exc)
        _bucket_checked = True
        return

    if cfg.bucket_name in names:
        logger.info("Supabase bucket '%s' already exists.", cfg.bucket_name)
    else:
        try:
            client.storage.create_bucket(
                cfg.bucket_name,
                options={
                    "public": cfg.public,
                    "file_size_limit": "10MB",
                    "allowed_mime_types": ["image/png", "image/jpeg", "image/webp", "video/mp4"],
                },
            )
            logger.info(
                "Created Supabase bucket '%s' (public=%s).",
                cfg.bucket_name, cfg.public,
            )
        except Exception as exc:
            # Bucket might've been created by a concurrent worker/request — not fatal.
            logger.warning("Could not create Supabase bucket '%s': %s", cfg.bucket_name, exc)

    _bucket_checked = True


def upload_file(contents: bytes, filename_hint: str, folder: str = "products") -> str:
    """Uploads bytes to Supabase Storage, returns the public (or signed) URL."""
    cfg = get_app_config().storage_config.supabase
    ext = Path(filename_hint).suffix.lower()
    key = f"{folder}/{uuid.uuid4().hex}{ext}"

    client = get_supabase()
    content_type = _guess_content_type(ext)

    client.storage.from_(cfg.bucket_name).upload(
        path=key,
        file=contents,
        file_options={"content-type": content_type, "upsert": "false"},
    )

    if cfg.public:
        return client.storage.from_(cfg.bucket_name).get_public_url(key)
    else:
        signed = client.storage.from_(cfg.bucket_name).create_signed_url(key, 60 * 60 * 24 * 365)
        return signed["signedURL"]


def delete_file(key_or_url: str, folder: str = "products") -> None:
    """Accepts either the storage key or a full URL and deletes the object."""
    cfg = get_app_config().storage_config.supabase
    key = key_or_url
    if key_or_url.startswith("http"):
        # extract the path portion after the bucket name in the URL
        key = key_or_url.split(f"/{cfg.bucket_name}/")[-1]
    try:
        get_supabase().storage.from_(cfg.bucket_name).remove([key])
    except Exception as exc:
        logger.warning("Could not delete storage object %s: %s", key, exc)


def _guess_content_type(ext: str) -> str:
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".webp": "image/webp", ".gif": "image/gif",
        ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
    }.get(ext, "application/octet-stream")

