import pytest
from pydantic import ValidationError

from schemas.auth import ChangePasswordRequest, LoginRequest, RegisterRequest, VerifyPasswordRequest


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


def test_verify_password_requires_non_empty() -> None:
    body = VerifyPasswordRequest(password="password123")
    assert body.password == "password123"
    with pytest.raises(ValidationError):
        VerifyPasswordRequest(password="")


def test_change_password_accepts_valid() -> None:
    body = ChangePasswordRequest(current_password="password123", new_password="newpassword456")
    assert body.current_password == "password123"
    assert body.new_password == "newpassword456"


def test_change_password_rejects_short_new() -> None:
    with pytest.raises(ValidationError) as exc:
        ChangePasswordRequest(current_password="password123", new_password="short")
    assert "new_password" in str(exc.value)


def test_change_password_requires_current() -> None:
    with pytest.raises(ValidationError):
        ChangePasswordRequest(current_password="", new_password="newpassword456")
