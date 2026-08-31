"""Fernet helpers for org BYOK provider keys at rest (ADR 0020).

The KEK lives in ``BYOK_ENCRYPTION_KEY``. Production refuses to boot without a
valid Fernet key (same posture as ``JWT_SECRET``). Development may omit it until
an org actually saves a key — encrypt/decrypt then raise ``ByokEncryptionError``.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from internal.config import settings


class ByokEncryptionError(Exception):
    """Missing/invalid KEK, or ciphertext that cannot be decrypted."""


def _fernet() -> Fernet:
    raw = (settings.byok_encryption_key or "").strip()
    if not raw:
        raise ByokEncryptionError(
            "BYOK_ENCRYPTION_KEY is not set. Generate one with "
            '`python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"`.'
        )
    try:
        return Fernet(raw.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise ByokEncryptionError(
            "BYOK_ENCRYPTION_KEY is not a valid Fernet key. Generate one with "
            '`python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"`.'
        ) from exc


def encrypt_key(raw: str) -> str:
    """Encrypt a provider API key; return the Fernet token as a str."""
    value = (raw or "").strip()
    if not value:
        raise ValueError("API key must not be empty")
    token = _fernet().encrypt(value.encode("utf-8"))
    return token.decode("ascii")


def decrypt_key(stored: str) -> str:
    """Decrypt a stored Fernet token back to the raw provider key."""
    token = (stored or "").strip()
    if not token:
        raise ByokEncryptionError("Encrypted key is empty")
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ByokEncryptionError(
            "Could not decrypt the stored key. The BYOK_ENCRYPTION_KEY may have changed."
        ) from exc
    except (ValueError, TypeError) as exc:
        raise ByokEncryptionError("Stored key is not a valid Fernet token.") from exc


def mask_key(raw: str) -> str:
    """Last four characters of a raw key (or the whole key if shorter)."""
    value = (raw or "").strip()
    if len(value) <= 4:
        return value
    return value[-4:]


def assert_byok_encryption_key_safe() -> None:
    """Refuse a missing / invalid Fernet KEK outside development."""
    raw = (settings.byok_encryption_key or "").strip()
    if settings.app_env == "development":
        if not raw:
            return
        _fernet()
        return
    if not raw:
        raise RuntimeError(
            "BYOK_ENCRYPTION_KEY is not set. Production requires a Fernet key to "
            "encrypt org provider keys at rest (ADR 0020). Generate one with "
            '`python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"`, or APP_ENV=development for local only.'
        )
    try:
        Fernet(raw.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            "BYOK_ENCRYPTION_KEY is not a valid Fernet key. Generate one with "
            '`python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"`.'
        ) from exc
