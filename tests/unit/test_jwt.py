import uuid

import pytest
from jose import jwt

from internal.auth.jwt import (
    TOKEN_TYPE_ACCESS,
    TOKEN_TYPE_REFRESH,
    create_access_token,
    create_refresh_jwt,
    decode_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from internal.config import settings


def test_hash_and_verify_password() -> None:
    hashed = hash_password("secret-password")
    assert hashed != "secret-password"
    assert verify_password("secret-password", hashed)
    assert not verify_password("wrong", hashed)


def test_hash_refresh_token_is_sha256_hex() -> None:
    token = generate_refresh_token()
    digest = hash_refresh_token(token)
    assert len(digest) == 64
    assert digest == hash_refresh_token(token)
    assert digest != hash_refresh_token(token + "x")


def test_access_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    token, expires = create_access_token(user_id)
    payload = decode_token(token, TOKEN_TYPE_ACCESS)
    assert payload["sub"] == str(user_id)
    assert payload["type"] == TOKEN_TYPE_ACCESS
    assert expires.tzinfo is not None


def test_refresh_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    family_id = uuid.uuid4()
    token, _ = create_refresh_jwt(user_id, family_id)
    payload = decode_token(token, TOKEN_TYPE_REFRESH)
    assert payload["sub"] == str(user_id)
    assert payload["family"] == str(family_id)
    assert payload["type"] == TOKEN_TYPE_REFRESH


def test_decode_rejects_wrong_type() -> None:
    user_id = uuid.uuid4()
    access, _ = create_access_token(user_id)
    with pytest.raises(ValueError, match="Invalid token type"):
        decode_token(access, TOKEN_TYPE_REFRESH)


def test_decode_rejects_tampered_token() -> None:
    user_id = uuid.uuid4()
    token, _ = create_access_token(user_id)
    with pytest.raises(ValueError, match="Invalid token"):
        decode_token(token + "tamper", TOKEN_TYPE_ACCESS)


def test_decode_rejects_wrong_secret() -> None:
    user_id = uuid.uuid4()
    token = jwt.encode(
        {"sub": str(user_id), "type": TOKEN_TYPE_ACCESS},
        "totally-wrong-secret-key-not-settings",
        algorithm="HS256",
    )
    with pytest.raises(ValueError, match="Invalid token"):
        decode_token(token, TOKEN_TYPE_ACCESS)


def test_settings_jwt_secret_used() -> None:
    user_id = uuid.uuid4()
    token, _ = create_access_token(user_id)
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    assert payload["sub"] == str(user_id)
