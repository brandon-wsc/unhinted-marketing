"""Step definitions for features/smoke.feature — shipped-behavior scaffold."""

from __future__ import annotations

from pytest_bdd import given, parsers, scenarios, then, when

from tests.api.helpers import auth_header, register_user

scenarios("../features/smoke.feature")


@given("a registered member")
def registered_member(api, bdd_ctx) -> None:
    body = api.run(register_user(api.client, email="bdd-smoke@example.com", password="password123"))
    bdd_ctx["member"] = {"email": body["user"]["email"], "password": "password123"}


@when(parsers.parse('the client requests "{method} {path}"'))
def request_path(api, bdd_ctx, method: str, path: str) -> None:
    bdd_ctx["res"] = api.request(method, path)


@when("the member logs in with the seeded password")
def member_login(api, bdd_ctx) -> None:
    member = bdd_ctx["member"]
    bdd_ctx["res"] = api.post(
        "/api/auth/login",
        json={"email": member["email"], "password": member["password"]},
    )


@when(parsers.parse('the member requests "{method} {path}" with the bearer token'))
def member_request(api, bdd_ctx, method: str, path: str) -> None:
    bdd_ctx["res"] = api.request(method, path, headers=auth_header(bdd_ctx["access_token"]))


@then(parsers.parse("the response status is {code:d}"))
def response_status(bdd_ctx, code: int) -> None:
    assert bdd_ctx["res"].status_code == code, bdd_ctx["res"].text


@then(parsers.parse('the response reports status "{status}"'))
def response_reports(bdd_ctx, status: str) -> None:
    assert bdd_ctx["res"].json()["status"] == status


@then("the member receives a bearer token")
def member_receives_token(bdd_ctx) -> None:
    body = bdd_ctx["res"].json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    bdd_ctx["access_token"] = body["access_token"]


@then("the profile email is the registered member's")
def profile_email_matches(bdd_ctx) -> None:
    assert bdd_ctx["res"].json()["email"] == bdd_ctx["member"]["email"]
