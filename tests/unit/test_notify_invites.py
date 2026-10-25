"""Unit tests for invite SMTP delivery (STARTTLS vs implicit TLS)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from internal.notify import invites


def _snap(**kwargs: object) -> SimpleNamespace:
    base = {
        "email_backend": "smtp",
        "email_from": "admin@unhinted.hk",
        "smtp_host": "smtp.mx.cloudflare.net",
        "smtp_port": 465,
        "smtp_user": "api_token",
        "smtp_password": "cf-token",
        "smtp_tls": True,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_send_smtp_port_465_uses_smtp_ssl() -> None:
    ssl_smtp = MagicMock()
    ssl_cm = MagicMock()
    ssl_cm.__enter__.return_value = ssl_smtp
    ssl_cm.__exit__.return_value = False

    with (
        patch.object(invites, "get_snapshot", return_value=_snap(smtp_port=465)),
        patch.object(invites.smtplib, "SMTP_SSL", return_value=ssl_cm) as smtp_ssl,
        patch.object(invites.smtplib, "SMTP") as smtp_plain,
    ):
        await invites._send_smtp(
            to_email="member@example.com",
            subject="Join Org on Unhinted",
            body="body",
        )

    smtp_ssl.assert_called_once_with("smtp.mx.cloudflare.net", 465, timeout=30)
    smtp_plain.assert_not_called()
    ssl_smtp.starttls.assert_not_called()
    ssl_smtp.login.assert_called_once_with("api_token", "cf-token")
    ssl_smtp.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_send_smtp_port_465_ignores_smtp_tls_flag() -> None:
    ssl_smtp = MagicMock()
    ssl_cm = MagicMock()
    ssl_cm.__enter__.return_value = ssl_smtp
    ssl_cm.__exit__.return_value = False

    with (
        patch.object(
            invites,
            "get_snapshot",
            return_value=_snap(smtp_port=465, smtp_tls=False),
        ),
        patch.object(invites.smtplib, "SMTP_SSL", return_value=ssl_cm) as smtp_ssl,
        patch.object(invites.smtplib, "SMTP") as smtp_plain,
    ):
        await invites._send_smtp(
            to_email="member@example.com",
            subject="x",
            body="y",
        )

    smtp_ssl.assert_called_once_with("smtp.mx.cloudflare.net", 465, timeout=30)
    smtp_plain.assert_not_called()
    ssl_smtp.starttls.assert_not_called()
    ssl_smtp.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_send_smtp_port_587_uses_starttls() -> None:
    plain_smtp = MagicMock()
    plain_cm = MagicMock()
    plain_cm.__enter__.return_value = plain_smtp
    plain_cm.__exit__.return_value = False

    with (
        patch.object(
            invites,
            "get_snapshot",
            return_value=_snap(
                smtp_host="smtp.resend.com",
                smtp_port=587,
                smtp_user="resend",
                smtp_password="re_xxx",
            ),
        ),
        patch.object(invites.smtplib, "SMTP", return_value=plain_cm) as smtp_plain,
        patch.object(invites.smtplib, "SMTP_SSL") as smtp_ssl,
    ):
        await invites._send_smtp(
            to_email="member@example.com",
            subject="Join Org on Unhinted",
            body="body",
        )

    smtp_plain.assert_called_once_with("smtp.resend.com", 587, timeout=30)
    smtp_ssl.assert_not_called()
    plain_smtp.starttls.assert_called_once()
    plain_smtp.login.assert_called_once_with("resend", "re_xxx")
    plain_smtp.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_send_smtp_skips_when_host_unset() -> None:
    with (
        patch.object(invites, "get_snapshot", return_value=_snap(smtp_host="")),
        patch.object(invites.smtplib, "SMTP_SSL") as smtp_ssl,
        patch.object(invites.smtplib, "SMTP") as smtp_plain,
    ):
        await invites._send_smtp(
            to_email="member@example.com",
            subject="x",
            body="y",
        )
    smtp_ssl.assert_not_called()
    smtp_plain.assert_not_called()


def test_use_implicit_tls_ports() -> None:
    assert invites._use_implicit_tls(465) is True
    assert invites._use_implicit_tls(587) is False
    assert invites._use_implicit_tls(25) is False
