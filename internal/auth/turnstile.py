"""Cloudflare Turnstile verification for auth endpoints."""

from __future__ import annotations

import logging

import httpx
from fastapi import HTTPException, Request, status

from internal.config import settings

logger = logging.getLogger(__name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def turnstile_required() -> bool:
    return settings.turnstile_enabled and bool((settings.turnstile_secret_key or "").strip())


async def enforce_turnstile(request: Request, token: str | None) -> None:
    """Verify Turnstile token when TURNSTILE_ENABLED and secret are set."""
    if not turnstile_required():
        return
    if not (token or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Turnstile verification required",
        )
    remote_ip = request.client.host if request.client else None
    payload: dict[str, str] = {
        "secret": settings.turnstile_secret_key or "",
        "response": token.strip(),
    }
    if remote_ip:
        payload["remoteip"] = remote_ip
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(TURNSTILE_VERIFY_URL, data=payload)
            res.raise_for_status()
            body = res.json()
    except httpx.HTTPError as exc:
        logger.warning("Turnstile siteverify request failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Turnstile verification unavailable",
        ) from exc
    if not body.get("success"):
        logger.info("Turnstile verification failed: %s", body.get("error-codes"))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Turnstile verification failed",
        )
