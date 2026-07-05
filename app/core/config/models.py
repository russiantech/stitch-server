
"""
app/core/config/models.py — Stitch Platform Configuration Models
"""

from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field, computed_field

class GeneralConfig(BaseModel):
    development_mode: bool = True
    api_version: str = "1.0.0"
    api_prefix: str = "/api/v1"
    site_name: str = "Stitch"
    site_description: str = "Stitch — Laundry & Fashion Operations Platform"
    contact_email: str = "hello@stitch.ng"
    timezone: str = "Africa/Lagos"


class CookieConfig(BaseModel):
    domain: str = "localhost"
    secure: bool = False
    httponly: bool = True
    samesite: Literal["lax", "strict", "none"] = "lax"
    max_age: int = 60 * 60 * 24 * 7


class S3Config(BaseModel):
    bucket_name: Optional[str] = None
    endpoint_url: Optional[str] = None
    region: str = "us-east-1"
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    use_ssl: bool = True


class ContentDeliveryConfig(BaseModel):
    type: Literal["filesystem", "s3api", "cloudinary"] = "filesystem"
    filesystem_base_path: str = "./uploads"
    max_file_size_mb: int = 50
    allowed_image_types: List[str] = ["image/jpeg", "image/png", "image/webp", "image/gif"]
    allowed_video_types: List[str] = ["video/mp4", "video/webm"]
    s3api: S3Config = S3Config()


class HostingConfig(BaseModel):
    domain: str = "localhost"
    ssl: bool = False
    port: int = 8000
    allowed_origins: List[str] = ["http://localhost:5173", "http://localhost:3000"]
    frontend_url: str = "http://localhost:5173"
    api_url_override: Optional[str] = Field(default=None, alias="api_url")
    cookie_config: CookieConfig = CookieConfig()
    content_delivery: ContentDeliveryConfig = ContentDeliveryConfig()

    @computed_field
    @property
    def api_url(self) -> str:
        if self.api_url_override:
            return self.api_url_override.rstrip("/")
        scheme = "https" if self.ssl else "http"
        if (self.ssl and self.port == 443) or (not self.ssl and self.port == 80):
            return f"{scheme}://{self.domain}"
        return f"{scheme}://{self.domain}:{self.port}"


class DatabaseConfig(BaseModel):
    sql_connection_string: Optional[str] = None
    pool_size: int = 20
    max_overflow: int = 40
    pool_recycle: int = 3600
    pool_timeout: int = 30
    echo: bool = False


class RedisConfig(BaseModel):
    redis_connection_string: Optional[str] = None
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    decode_responses: bool = True
    default_ttl: int = 3600
    session_ttl: int = 86400


class SecurityConfig(BaseModel):
    auth_jwt_secret_key: str = "CHANGE_ME_INSECURE_DEFAULT"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24        # 24 h
    refresh_token_expire_minutes: int = 60 * 24 * 7   # 7 days
    jwt_secret_key: str = "FALLBACK_SECRET"
    password_reset_token_expire_minutes: int = 15
    email_verification_token_expire_minutes: int = 60 * 24
    bcrypt_rounds: int = 12
    cors_allowed_origins: List[str] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    super_admin_emails: List[str] = Field(default_factory=list)
    # OTP
    signup_otp_ttl_seconds: int = 600
    password_reset_otp_ttl_seconds: int = 900


class MailConfig(BaseModel):
    system_email_address: str = "no-reply@stitch.ng"
    mail_sender_name: str = "Stitch"
    mail_sender_email: str = "no-reply@stitch.ng"
    provider: Literal["smtp", "resend", "sendgrid", "console"] = "console"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    resend_api_key: Optional[str] = None
    sendgrid_api_key: Optional[str] = None
    templates_dir: str = "./app/templates/email"


class PaystackConfig(BaseModel):
    secret_key: Optional[str] = None
    public_key: Optional[str] = None
    base_url: str = "https://api.paystack.co"
    callback_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    timeout: int = 30


class PaymentsConfig(BaseModel):
    currency: str = "NGN"
    paystack: PaystackConfig = PaystackConfig()


class MonitoringConfig(BaseModel):
    sentry_dsn: Optional[str] = None
    sentry_environment: str = "development"
    enable_health_checks: bool = True


class AppConfig(BaseModel):
    general_config: GeneralConfig = GeneralConfig()
    hosting_config: HostingConfig = HostingConfig()
    database_config: DatabaseConfig = DatabaseConfig()
    redis_config: RedisConfig = RedisConfig()
    security_config: SecurityConfig = Field(
        default_factory=lambda: SecurityConfig(auth_jwt_secret_key="CHANGE_ME")
    )
    mail_config: MailConfig = MailConfig()
    payments_config: PaymentsConfig = PaymentsConfig()
    monitoring_config: MonitoringConfig = MonitoringConfig()

    @computed_field
    @property
    def cors_origins(self) -> List[str]:
        origins = self.hosting_config.allowed_origins
        return origins or ["http://localhost:5173"]


