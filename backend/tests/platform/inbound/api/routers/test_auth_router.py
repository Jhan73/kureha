import json
import uuid

import httpx

from app.main import app
from app.platform.inbound.api.access_control.dependencies import get_http_client
from tests.platform.inbound.api.routers.conftest import (
    auth_headers,
    count_audit_rows,
    mint_access_token,
    seed_reception_actor,
)


def _fake_supabase_transport(*, subject: str, email: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "user": {
                    "id": subject,
                    "email": email,
                    "email_confirmed_at": "2026-01-01T00:00:00Z",
                }
            },
        )

    return httpx.MockTransport(handler)


def test_login_succeeds_end_to_end_and_the_returned_token_is_usable(client) -> None:
    actor = seed_reception_actor(email="reception1@example.com")

    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        base_url="https://fake-supabase.test",
        transport=_fake_supabase_transport(subject="supabase-sub-1", email=actor["email"]),
    )
    try:
        response = client.post(
            "/auth/login",
            json={"tenant_id": actor["tenant_id"], "email": actor["email"], "password": "whatever"},
        )
    finally:
        app.dependency_overrides.pop(get_http_client, None)

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "reception"
    assert body["user_id"] == actor["user_id"]
    assert body["access_token"]
    assert body["refresh_token"]

    # The minted access token is genuinely usable against an authenticated
    # route -- proves the full mint -> verify -> live-actor-resolve chain,
    # not just that `Login` returned SOME string.
    logout_response = client.post(
        "/auth/logout",
        json={"refresh_token": body["refresh_token"]},
        headers=auth_headers(body["access_token"]),
    )
    assert logout_response.status_code == 204


def test_logout_without_a_token_is_denied(client) -> None:
    response = client.post("/auth/logout", json={"refresh_token": "does-not-matter"})

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_logout_with_a_garbage_token_is_denied(client) -> None:
    response = client.post(
        "/auth/logout",
        json={"refresh_token": "does-not-matter"},
        headers=auth_headers("this-is-not-a-real-jwt"),
    )

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_logout_with_a_valid_token_but_a_refresh_token_that_does_not_exist_returns_the_not_found_envelope(
    client,
) -> None:
    actor = seed_reception_actor(email="reception2@example.com")
    token = mint_access_token(
        tenant_id=actor["tenant_id"], site_id=actor["site_id"], role="reception", user_id=actor["user_id"]
    )

    response = client.post(
        "/auth/logout", json={"refresh_token": "no-such-refresh-token"}, headers=auth_headers(token)
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "not_found"
    assert body["category"] == "validation"


def _fake_supabase_transport_with_accounts(accounts: dict[str, tuple[str, str]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        account = accounts.get(body.get("email"))
        if account is None or account[1] != body.get("password"):
            return httpx.Response(400, json={"error": "invalid_grant"})
        subject, _ = account
        return httpx.Response(
            200,
            json={
                "user": {
                    "id": subject,
                    "email": body["email"],
                    "email_confirmed_at": "2026-01-01T00:00:00Z",
                }
            },
        )

    return httpx.MockTransport(handler)


def test_five_login_attempts_are_processed_and_a_sixth_is_denied_even_with_the_correct_password_and_is_tenant_and_email_scoped_and_audited(
    client,
) -> None:
    unique = uuid.uuid4().hex
    email = f"acct-limit-{unique}@example.com"
    other_email = f"acct-limit-other-{unique}@example.com"
    correct_password = "the-correct-password"

    actor = seed_reception_actor(email=email)
    other_tenant_actor = seed_reception_actor(email=email)

    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        base_url="https://fake-supabase.test",
        transport=_fake_supabase_transport_with_accounts({email: ("supabase-sub-acct-limit", correct_password)}),
    )
    try:
        # (a) 5 wrong-password attempts against tenant A: processed (401
        # InvalidCredentialsError), not yet blocked.
        for _ in range(5):
            response = client.post(
                "/auth/login",
                json={"tenant_id": actor["tenant_id"], "email": email, "password": "wrong-password"},
            )
            assert response.status_code == 401

        # (b) 6th attempt, even with the CORRECT password, is denied.
        sixth_response = client.post(
            "/auth/login",
            json={"tenant_id": actor["tenant_id"], "email": email, "password": correct_password},
        )
        assert sixth_response.status_code == 429
        sixth_body = sixth_response.json()
        assert sixth_body["error_code"] == "rate_limited"
        assert sixth_body["retryable"] is True

        # (c) a different email, same tenant, is not blocked.
        other_email_response = client.post(
            "/auth/login",
            json={"tenant_id": actor["tenant_id"], "email": other_email, "password": "whatever"},
        )
        assert other_email_response.status_code != 429

        # (d) the same email, a different tenant, is not blocked -- and
        # actually succeeds, proving the subject is genuinely tenant-scoped.
        other_tenant_response = client.post(
            "/auth/login",
            json={"tenant_id": other_tenant_actor["tenant_id"], "email": email, "password": correct_password},
        )
        assert other_tenant_response.status_code == 200
    finally:
        app.dependency_overrides.pop(get_http_client, None)

    # (e) exactly one audit row, under tenant A's REAL tenant_id.
    assert count_audit_rows(actor["tenant_id"], "auth.rate_limited") == 1
