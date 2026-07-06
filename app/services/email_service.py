"""
app/services/email_service.py — Multi-provider email service for Stitch.
Providers: console (dev) | smtp | resend | sendgrid
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from app.core.exceptions.custom_exceptions import EmailServiceError

from app.core.config import get_app_config

logger = logging.getLogger(__name__)

_jinja: Optional[Environment] = None


def _get_jinja() -> Environment:
    global _jinja
    if _jinja is None:
        tpl_dir = Path(__file__).parent.parent / "templates" / "emails"
        _jinja = Environment(
            loader=FileSystemLoader(str(tpl_dir)),
            autoescape=select_autoescape(["html"]),
        )
    return _jinja


def _render(template_name: str, context: dict) -> str:
    try:
        tpl = _get_jinja().get_template(template_name)
        return tpl.render(**context)
    except Exception as exc:
        logger.error("Template render error [%s]: %s", template_name, exc)
        return f"<p>{context.get('message', 'No message')}</p>"


# ─── Providers ────────────────────────────────────────────────────────────────

def _send_console(to: List[str], subject: str, html: str) -> bool:
    logger.info("📧 [EMAIL-CONSOLE] To=%s | Subject=%s", to, subject)
    logger.debug("Body:\n%s", html[:400])
    return True


def _send_smtp(to: List[str], subject: str, html: str) -> bool:
    cfg = get_app_config().mail_config
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{cfg.mail_sender_name} <{cfg.mail_sender_email}>"
    msg["To"]      = ", ".join(to)
    msg.attach(MIMEText(html, "html"))
    try:
        if cfg.smtp_use_ssl:
            server = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port)
        else:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port)
        if cfg.smtp_use_tls and not cfg.smtp_use_ssl:
            server.starttls()
        if cfg.smtp_username and cfg.smtp_password:
            server.login(cfg.smtp_username, cfg.smtp_password)
        server.sendmail(cfg.mail_sender_email, to, msg.as_string())
        server.quit()
        logger.info("SMTP email sent to %s", to)
        return True
    except smtplib.SMTPException as exc:
        logger.error("SMTP error: %s", exc)
        return False


def _send_resend(to: List[str], subject: str, html: str) -> bool:
    cfg = get_app_config().mail_config
    if not cfg.resend_api_key:
        logger.warning("Resend API key not configured, falling back to console")
        return _send_console(to, subject, html)
    try:
        import resend
        resend.api_key = cfg.resend_api_key
        resend.Emails.send({
            "from":    f"{cfg.mail_sender_name} <{cfg.mail_sender_email}>",
            "to":      to,
            "subject": subject,
            "html":    html,
        })
        logger.info("Resend email sent to %s", to)
        return True
    except Exception as exc:
        logger.error("Resend error: %s", exc)
        return False


# ─── Public send function ──────────────────────────────────────────────────────

# v1
# def send_email(
#     to: str | List[str],
#     subject: str,
#     template: str,
#     context: Optional[dict] = None,
#     html: Optional[str] = None,
# ) -> bool:
#     cfg = get_app_config().mail_config
#     recipients = [to] if isinstance(to, str) else to
#     body = html or _render(template, context or {})

#     dispatch = {
#         "console": _send_console,
#         "smtp":    _send_smtp,
#         "resend":  _send_resend,
#     }.get(cfg.provider, _send_console)

#     try:
#         return dispatch(recipients, subject, body)
#     except Exception as exc:
#         logger.error("send_email error: %s", exc)
#         return False


# v2
# def send_email(
#     to: str | List[str],
#     subject: str,
#     template: str,
#     context: Optional[dict] = None,
#     html: Optional[str] = None,
# ) -> bool:
#     cfg = get_app_config().mail_config
#     recipients = [to] if isinstance(to, str) else to
#     body = html or _render(template, context or {})

#     dispatch = {
#         "console": _send_console,
#         "smtp":    _send_smtp,
#         "resend":  _send_resend,
#     }.get(cfg.provider, _send_console)

#     try:
#         return dispatch(recipients, subject, body)
#     except Exception as exc:
#         logger.error("send_email error: %s", exc)
#         raise EmailServiceError(str(exc)) from exc   # <-- propagate


# v3
from app.core.exceptions.custom_exceptions import EmailServiceError

# ... existing code ...

def send_email(
    to: str | List[str],
    subject: str,
    template: str,
    context: Optional[dict] = None,
    html: Optional[str] = None,
) -> bool:
    cfg = get_app_config().mail_config
    recipients = [to] if isinstance(to, str) else to
    body = html or _render(template, context or {})

    dispatch = {
        "console": _send_console,
        "smtp":    _send_smtp,
        "resend":  _send_resend,
    }.get(cfg.provider, _send_console)

    try:
        success = dispatch(recipients, subject, body)
        if not success:
            raise EmailServiceError(
                f"Email provider '{cfg.provider}' returned failure.",
                provider=cfg.provider,
            )
        return True
    except EmailServiceError:
        raise
    except Exception as exc:
        logger.error("send_email error: %s", exc)
        raise EmailServiceError(str(exc), provider=cfg.provider) from exc

# ─── Typed email helpers ───────────────────────────────────────────────────────

def send_welcome(email: str, name: str) -> bool:
    cfg = get_app_config()
    return send_email(
        to=email, subject=f"Welcome to {cfg.general_config.site_name}! ✂️",
        template="welcome.html",
        context={"name": name, "site_name": cfg.general_config.site_name,
                 "frontend_url": cfg.hosting_config.frontend_url},
    )


def send_otp(email: str, name: str, otp: str, purpose: str = "verify") -> bool:
    subjects = {
        "verify": "Verify your Stitch account",
        "reset":  "Reset your Stitch password",
        "login":  "Your Stitch login code",
    }
    return send_email(
        to=email, subject=subjects.get(purpose, "Your OTP"),
        template="otp.html",
        context={
            "name": name, 
            "otp": otp, 
            "purpose": purpose,
            "site_name": get_app_config().general_config.site_name
        },
    )


def send_order_confirmed(email: str, name: str, order_ref: str, order_type: str, total: str) -> bool:
    cfg = get_app_config()
    return send_email(
        to=email, subject=f"Order {order_ref} confirmed — Stitch",
        template="order_confirmed.html",
        context={"name": name, "order_ref": order_ref, "order_type": order_type,
                 "total": total, "frontend_url": cfg.hosting_config.frontend_url},
    )


def send_subscription_activated(email: str, name: str, plan_name: str, units: int, renews_at: str) -> bool:
    return send_email(
        to=email, subject=f"Subscription active — {plan_name}",
        template="subscription_activated.html",
        context={"name": name, "plan_name": plan_name, "units": units, "renews_at": renews_at},
    )


def send_invite(email: str, inviter_name: str, role: str, invite_url: str) -> bool:
    return send_email(
        to=email, subject="You've been invited to join Stitch",
        template="invite.html",
        context={"inviter": inviter_name, "role": role, "invite_url": invite_url,
                 "site_name": get_app_config().general_config.site_name},
    )


def send_order_status_update(email: str, name: str, order_ref: str, new_status: str) -> bool:
    return send_email(
        to=email, subject=f"Order {order_ref} — Status update",
        template="order_status.html",
        context={"name": name, "order_ref": order_ref, "status": new_status,
                 "frontend_url": get_app_config().hosting_config.frontend_url},
    )

