import pytest
from pydantic import ValidationError

from schemas.auth import LoginRequest, RegisterRequest


def test_register_rejects_short_password() -> None:
    with pytest.raises(ValidationError) as exc:
        RegisterRequest(
            email="a@example.com",
            password="short",
            display_name="A",
        )
    assert "password" in str(exc.value).lower()


def test_register_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="not-an-email",
            password="password123",
            display_name="A",
        )


def test_register_accepts_valid() -> None:
    body = RegisterRequest(
        email="ok@example.com",
        password="password123",
        display_name="Ok",
        organization_name="Acme",
    )
    assert body.email == "ok@example.com"
    assert body.organization_name == "Acme"


def test_login_requires_password() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(email="a@example.com", password="")
