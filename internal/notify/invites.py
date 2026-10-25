"""Org invite email delivery — pluggable backends (link / smtp / console)."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from internal.instance.config import get_snapshot

logger = logging.getLogger(__name__)

# Implicit TLS (SMTPS). Cloudflare Email Sending only supports this on :465 —
# not STARTTLS on :587. See https://developers.cloudflare.com/email-service/api/send-emails/smtp/
_IMPLICIT_TLS_PORTS = frozenset({465})


def _use_implicit_tls(port: int) -> bool:
    return port in _IMPLICIT_TLS_PORTS


async def send_invite_email(
    *,
    to_email: str,
    invite_url: str,
    organization_name: str,
) -> None:
    """Best-effort invite delivery; failures are logged and never block the API."""
    snap = get_snapshot()
    backend = snap.email_backend
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
    snap = get_snapshot()
    if not snap.smtp_host:
        logger.warning("email_backend=smtp but smtp_host is unset — skipping send to %s", to_email)
        return

    def _send() -> None:
        msg = EmailMessage()
        msg["From"] = snap.email_from
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)
        # Port 465 opens TLS immediately (Cloudflare Email Sending, etc.) —
        # no STARTTLS; smtp_tls only applies to upgrade ports like 587.
        implicit_tls = _use_implicit_tls(snap.smtp_port)
        smtp_cls = smtplib.SMTP_SSL if implicit_tls else smtplib.SMTP
        with smtp_cls(snap.smtp_host, snap.smtp_port, timeout=30) as smtp:
            if not implicit_tls and snap.smtp_tls:
                smtp.starttls()
            if snap.smtp_user:
                smtp.login(snap.smtp_user, snap.smtp_password or "")
            smtp.send_message(msg)

    await asyncio.to_thread(_send)
