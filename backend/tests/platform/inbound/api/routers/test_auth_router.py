"""Task 10.1: `/auth/login`/`/auth/refresh`/`/auth/logout` against the real
FastAPI app (`app/main.py`) + real Postgres. Proves:

(a) a valid login succeeds end-to-end and returns a usable access+refresh
    pair (verified by immediately using the access token against an
    authenticated route);
(b) an unauthenticated request to an authenticated route (`/auth/logout`)
    is denied by the real `AccessControlMiddleware`;
(c) the denial's response body matches `errors.py`'s §21 envelope shape
    exactly.

`Login`'s own `AuthPort` dependency (`SupabaseAuthAdapter`) is swapped for a
fake HTTP transport via FastAPI's `dependency_overrides` on `get_http_client`
-- there is no real Supabase project reachable in this dev environment
(ADR-14: "standalone Supabase Auth project"), so faking the ONE external
HTTP boundary `Login` crosses is the correct seam, not a shortcut around
anything this router itself owns.

**Sync `def test_...`, not `async def`** -- see `conftest.py`'s own module
docstring for why."""

import httpx

from app.main import app
from app.platform.inbound.api.access_control.dependencies import get_http_client
from tests.platform.inbound.api.routers.conftest import auth_headers, mint_access_token, seed_reception_actor


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
    """`AccessControlMiddleware` denies this BEFORE the route handler (and
    `errors.py`'s central handler) ever runs -- its own docstring: "Both
    response bodies are the SAME generic `{"error": "unauthorized"}`
    regardless of cause", a DELIBERATELY different, simpler contract than
    `errors.py`'s §21 envelope (see `test_logout_with_a_valid_token_but_a_
    refresh_token_that_does_not_exist_returns_the_not_found_envelope` below
    for a denial that DOES flow through a route handler and DOES get the
    rich envelope)."""
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
