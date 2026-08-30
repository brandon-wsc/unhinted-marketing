"""Unit tests for BYOK Fernet helpers (no live network, no DB)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from internal.llm.keys import (
    ByokEncryptionError,
    assert_byok_encryption_key_safe,
    decrypt_key,
    encrypt_key,
    mask_key,
)


def _set_kek(monkeypatch: pytest.MonkeyPatch, key: str | None) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "byok_encryption_key", key)


def test_encrypt_decrypt_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    kek = Fernet.generate_key().decode()
    _set_kek(monkeypatch, kek)
    token = encrypt_key("sk-live-example-secret")
    assert token != "sk-live-example-secret"
    assert decrypt_key(token) == "sk-live-example-secret"


def test_encrypt_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_kek(monkeypatch, Fernet.generate_key().decode())
    token = encrypt_key("  sk-padded  \n")
    assert decrypt_key(token) == "sk-padded"


def test_encrypt_rejects_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_kek(monkeypatch, Fernet.generate_key().decode())
    with pytest.raises(ValueError, match="must not be empty"):
        encrypt_key("   ")


def test_encrypt_without_kek_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_kek(monkeypatch, None)
    with pytest.raises(ByokEncryptionError, match="BYOK_ENCRYPTION_KEY is not set"):
        encrypt_key("sk-anything")


def test_decrypt_wrong_kek_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_kek(monkeypatch, Fernet.generate_key().decode())
    token = encrypt_key("sk-live")
    _set_kek(monkeypatch, Fernet.generate_key().decode())
    with pytest.raises(ByokEncryptionError, match="Could not decrypt"):
        decrypt_key(token)


def test_decrypt_garbage_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_kek(monkeypatch, Fernet.generate_key().decode())
    with pytest.raises(ByokEncryptionError):
        decrypt_key("not-a-fernet-token")


def test_mask_key() -> None:
    assert mask_key("sk-abcdefghijklmnop") == "mnop"
    assert mask_key("  sk-abcdefghijklmnop  ") == "mnop"
    assert mask_key("ab") == "ab"
    assert mask_key("") == ""


def test_assert_development_allows_missing_kek(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "app_env", "development")
    _set_kek(monkeypatch, None)
    assert_byok_encryption_key_safe()


def test_assert_development_rejects_invalid_kek_if_set(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "app_env", "development")
    _set_kek(monkeypatch, "not-a-fernet-key")
    with pytest.raises(ByokEncryptionError, match="not a valid Fernet key"):
        assert_byok_encryption_key_safe()


def test_assert_production_requires_valid_kek(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "app_env", "production")
    _set_kek(monkeypatch, None)
    with pytest.raises(RuntimeError, match="BYOK_ENCRYPTION_KEY is not set"):
        assert_byok_encryption_key_safe()

    _set_kek(monkeypatch, "too-short")
    with pytest.raises(RuntimeError, match="not a valid Fernet key"):
        assert_byok_encryption_key_safe()

    _set_kek(monkeypatch, Fernet.generate_key().decode())
    assert_byok_encryption_key_safe()
