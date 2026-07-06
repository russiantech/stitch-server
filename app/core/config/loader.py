
"""
app/core/config/loader.py — Environment-driven config loader for Stitch
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .models import (
    AppConfig, CloudinaryConfig, GeneralConfig, HostingConfig, DatabaseConfig,
    RedisConfig, SecurityConfig, MailConfig, PaymentsConfig,
    PaystackConfig, S3Config, CookieConfig,
    MonitoringConfig, StorageConfig, SupabaseStorageConfig,
)

# Load .env from project root (server/) or parent
for _candidate in ["server/.env", ".env", "../.env"]:
    if Path(_candidate).exists():
        load_dotenv(_candidate, override=False)
        break


def _b(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes")


def _i(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _list(key: str, default: Optional[list] = None) -> list:
    raw = os.getenv(key, "")
    if not raw:
        return default or []
    return [item.strip() for item in raw.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_app_config() -> AppConfig:
    return AppConfig(
        general_config=GeneralConfig(
            development_mode=_b("APP_DEVELOPMENT_MODE", True),
            api_version=os.getenv("APP_API_VERSION", "1.0.0"),
            api_prefix=os.getenv("APP_API_PREFIX", "/api/v1"),
            site_name=os.getenv("APP_SITE_NAME", "Stitch"),
            site_description=os.getenv(
                "APP_SITE_DESCRIPTION",
                "Stitch — Laundry & Fashion Operations Platform",
            ),
            contact_email=os.getenv("APP_CONTACT_EMAIL", "hello@stitch.ng"),
            timezone=os.getenv("APP_TIMEZONE", "Africa/Lagos"),
        ),
        
        # hosting_config=HostingConfig(
        #     domain=os.getenv("APP_DOMAIN", "localhost"),
        #     ssl=_b("APP_SSL"),
        #     port=_i("APP_PORT", 8000),
        #     allowed_origins=_list(
        #         "APP_ALLOWED_ORIGINS",
        #         ["http://localhost:5173", "http://localhost:3000"],
        #     ),
        #     frontend_url=os.getenv("APP_FRONTEND_URL", "http://localhost:5173"),
        #     api_url_override=os.getenv("APP_API_URL"),
        #     cookie_config=CookieConfig(
        #         domain=os.getenv("APP_COOKIE_DOMAIN", "localhost"),
        #         secure=_b("APP_COOKIE_SECURE"),
        #         samesite=os.getenv("APP_COOKIE_SAMESITE", "lax"),  # type: ignore
        #     ),
        # ),
        
        # content_delivery_config=ContentDeliveryConfig(
        #     type=os.getenv("APP_CONTENT_DELIVERY_TYPE", "filesystem"),  # type: ignore
        #     filesystem_base_path=os.getenv("APP_FILESYSTEM_BASE_PATH", "./uploads"),
        #     max_file_size_mb=_i("APP_MAX_FILE_SIZE_MB", 50),
        #     s3api=S3Config(
        #         bucket_name=os.getenv("APP_S3_BUCKET_NAME"),
        #         endpoint_url=os.getenv("APP_S3_ENDPOINT_URL"),
        #         region=os.getenv("APP_S3_REGION", "us-east-1"),
        #         access_key_id=os.getenv("APP_S3_ACCESS_KEY_ID"),
        #         secret_access_key=os.getenv("APP_S3_SECRET_ACCESS_KEY"),
        #     ),
            
        #     supabase=SupabaseStorageConfig(
        #         url=os.getenv("APP_SUPABASE_URL"),
        #         service_role_key=os.getenv("APP_SUPABASE_SERVICE_ROLE_KEY"),
        #         bucket_name=os.getenv("APP_SUPABASE_BUCKET", "products"),
        #         public=_b("APP_SUPABASE_BUCKET_PUBLIC", True),
        #     ),
        # ),
        
        # v2
        hosting_config=HostingConfig(
        domain=os.getenv("APP_DOMAIN", "localhost"),
        ssl=_b("APP_SSL"),
        port=_i("APP_PORT", 8000),
        allowed_origins=_list(
            "APP_ALLOWED_ORIGINS",
            ["http://localhost:5173", "http://localhost:3000"],
        ),
        frontend_url=os.getenv("APP_FRONTEND_URL", "http://localhost:5173"),
        api_url_override=os.getenv("APP_API_URL"),
        cookie_config=CookieConfig(
            domain=os.getenv("APP_COOKIE_DOMAIN", "localhost"),
            secure=_b("APP_COOKIE_SECURE"),
            samesite=os.getenv("APP_COOKIE_SAMESITE", "lax"),
        ),
        ),
        storage_config=StorageConfig(
            provider=os.getenv("APP_STORAGE_PROVIDER", "supabase"),
            max_file_size_mb=_i("APP_MAX_FILE_SIZE_MB", 50),
            allowed_image_types=_list(
                "APP_ALLOWED_IMAGE_TYPES",
                ["image/jpeg", "image/png", "image/webp", "image/gif"],
            ),
            allowed_video_types=_list(
                "APP_ALLOWED_VIDEO_TYPES",
                ["video/mp4", "video/webm"],
            ),
            filesystem_base_path=os.getenv("APP_FILESYSTEM_BASE_PATH", "./uploads"),
            s3=S3Config(
                bucket_name=os.getenv("APP_S3_BUCKET_NAME"),
                endpoint_url=os.getenv("APP_S3_ENDPOINT_URL"),
                region=os.getenv("APP_S3_REGION", "us-east-1"),
                access_key_id=os.getenv("APP_S3_ACCESS_KEY_ID"),
                secret_access_key=os.getenv("APP_S3_SECRET_ACCESS_KEY"),
            ),
            supabase=SupabaseStorageConfig(
                url=os.getenv("APP_SUPABASE_URL"),
                service_role_key=os.getenv("APP_SUPABASE_SERVICE_ROLE_KEY"),
                bucket_name=os.getenv("APP_SUPABASE_BUCKET", "products"),
                public=_b("APP_SUPABASE_BUCKET_PUBLIC", True),
            ),
            cloudinary=CloudinaryConfig(
                cloud_name=os.getenv("APP_CLOUDINARY_CLOUD_NAME"),
                api_key=os.getenv("APP_CLOUDINARY_API_KEY"),
                api_secret=os.getenv("APP_CLOUDINARY_API_SECRET"),
            ),
        ),

        database_config=DatabaseConfig(
            sql_connection_string=os.getenv("APP_SQL_CONNECTION_STRING"),
            pool_size=_i("APP_DB_POOL_SIZE", 20),
            max_overflow=_i("APP_DB_MAX_OVERFLOW", 40),
            pool_recycle=_i("APP_DB_POOL_RECYCLE", 3600),
            pool_timeout=_i("APP_DB_POOL_TIMEOUT", 30),
            echo=_b("APP_DB_ECHO"),
        ),
        
        redis_config=RedisConfig(
            redis_connection_string=os.getenv("APP_REDIS_CONNECTION_STRING"),
            host=os.getenv("APP_REDIS_HOST", "localhost"),
            port=_i("APP_REDIS_PORT", 6379),
            db=_i("APP_REDIS_DB", 0),
            password=os.getenv("APP_REDIS_PASSWORD"),
            default_ttl=_i("APP_REDIS_DEFAULT_TTL", 3600),
            session_ttl=_i("APP_REDIS_SESSION_TTL", 86400),
        ),
        
        security_config=SecurityConfig(
            auth_jwt_secret_key=os.getenv(
                "APP_AUTH_JWT_SECRET_KEY", "CHANGE_ME_INSECURE_DEFAULT"
            ),
            jwt_algorithm=os.getenv("APP_JWT_ALGORITHM", "HS256"),
            access_token_expire_minutes=_i("APP_ACCESS_TOKEN_EXPIRE_MINUTES", 1440),
            refresh_token_expire_minutes=_i("APP_REFRESH_TOKEN_EXPIRE_MINUTES", 10080),
            bcrypt_rounds=_i("APP_BCRYPT_ROUNDS", 12),
            cors_allowed_origins=_list(
                "APP_CORS_ALLOWED_ORIGINS",
                ["http://localhost:5173"],
            ),
            super_admin_emails=_list("APP_SUPER_ADMIN_EMAILS"),
        ),
        
        mail_config=MailConfig(
            system_email_address=os.getenv("APP_SYSTEM_EMAIL", "no-reply@stitch.ng"),
            mail_sender_name=os.getenv("APP_MAIL_SENDER_NAME", "Stitch"),
            mail_sender_email=os.getenv("APP_MAIL_SENDER_EMAIL", "no-reply@stitch.ng"),
            provider=os.getenv("APP_MAIL_PROVIDER", "console"),  # type: ignore
            smtp_host=os.getenv("APP_SMTP_HOST", "smtp.gmail.com"),
            smtp_port=_i("APP_SMTP_PORT", 587),
            smtp_username=os.getenv("APP_SMTP_USERNAME"),
            smtp_password=os.getenv("APP_SMTP_PASSWORD"),
            smtp_use_tls=_b("APP_SMTP_USE_TLS", True),
            resend_api_key=os.getenv("APP_RESEND_API_KEY"),
        ),
        
        payments_config=PaymentsConfig(
            currency=os.getenv("APP_PAYMENTS_CURRENCY", "NGN"),
            paystack=PaystackConfig(
                secret_key=os.getenv("APP_PAYSTACK_SECRET_KEY"),
                public_key=os.getenv("APP_PAYSTACK_PUBLIC_KEY"),
                callback_url=os.getenv(
                    "APP_PAYSTACK_CALLBACK_URL",
                    "http://localhost:5173/subscriptions?verify=1",
                ),
                webhook_secret=os.getenv("PAYSTACK_WEBHOOK_SECRET"),
            ),
        ),
        
        monitoring_config=MonitoringConfig(
            sentry_dsn=os.getenv("APP_SENTRY_DSN"),
            sentry_environment=os.getenv("APP_SENTRY_ENV", "development"),
        ),
    )

