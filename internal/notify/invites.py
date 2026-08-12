"""Org invite email delivery — pluggable backends (link / smtp / console)."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from internal.config import settings

logger = logging.getLogger(__name__)


async def send_invite_email(
    *,
    to_email: str,
    invite_url: str,
    organization_name: str,
) -> None:
    """Best-effort invite delivery; failures are logged and never block the API."""
    backend = (settings.email_backend or "link").strip().lower()
    subject = f"Join {organization_name} on Unhinted"
    body = (
        f"You have been invited to join {organization_name}.\n\n"
        f"Open this link to accept (register or log in with {to_email} first):\n"
        f"{invite_url}\n"
    )

    try:
        if backend == "console":
            logger.info(
                "invite email to=%s org=%s url=%s\n%s",
                to_email,
                organization_name,
                invite_url,
                body,
            )
        elif backend == "smtp":
            await _send_smtp(to_email=to_email, subject=subject, body=body)
        # link: UI copies invite_url; no outbound email
    except Exception:
        logger.exception("invite email delivery failed for %s", to_email)


async def _send_smtp(*, to_email: str, subject: str, body: str) -> None:
    if not settings.smtp_host:
        logger.warning("EMAIL_BACKEND=smtp but SMTP_HOST is unset — skipping send to %s", to_email)
        return

    def _send() -> None:
        msg = EmailMessage()
        msg["From"] = settings.email_from
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            if settings.smtp_tls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password or "")
            smtp.send_message(msg)

    await asyncio.to_thread(_send)
