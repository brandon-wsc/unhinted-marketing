import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from internal.config import settings

password_hasher = PasswordHash.recommended()

ALGORITHM = "HS256"
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return password_hasher.verify(plain, hashed)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def create_access_token(user_id: uuid.UUID) -> tuple[str, datetime]:
    expires = datetime.now(UTC) + timedelta(minutes=settings.jwt_access_expire_minutes)
    payload = {
        "sub": str(user_id),
        "type": TOKEN_TYPE_ACCESS,
        "exp": expires,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM), expires


def create_refresh_jwt(user_id: uuid.UUID, family_id: uuid.UUID) -> tuple[str, datetime]:
    expires = datetime.now(UTC) + timedelta(days=settings.jwt_refresh_expire_days)
    payload = {
        "sub": str(user_id),
        "type": TOKEN_TYPE_REFRESH,
        "family": str(family_id),
        "exp": expires,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM), expires


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError as exc:
        raise ValueError("Invalid token") from exc
    if payload.get("type") != expected_type:
        raise ValueError("Invalid token type")
    return payload
