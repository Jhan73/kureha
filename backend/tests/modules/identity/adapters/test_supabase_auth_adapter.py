"""Task 4.2: `SupabaseAuthAdapter` -- `AuthPort` impl over Supabase Auth
(GoTrue)'s REST API (design.md §17.2/ADR-14). No real network: `httpx`'s
`MockTransport` stands in for Supabase's HTTP surface, asserting on the
exact request shape (method/path/body/headers) and mapping Supabase's
response shapes to `AuthnResult`/`InvalidCredentialsError`."""

import httpx
import pytest

from app.modules.identity.adapters.outbound.auth.supabase_auth_adapter import SupabaseAuthAdapter
from app.modules.identity.domain.errors import InvalidCredentialsError

_BASE_URL = "https://project-ref.supabase.co"
_API_KEY = "test-anon-key"


def _adapter(handler) -> SupabaseAuthAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SupabaseAuthAdapter(base_url=_BASE_URL, api_key=_API_KEY, http_client=client)


@pytest.mark.asyncio
async def test_verify_password_returns_authn_result_on_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/auth/v1/token"
        assert request.url.params["grant_type"] == "password"
        assert request.headers["apikey"] == _API_KEY
        return httpx.Response(
            200,
            json={
                "access_token": "supabase-jwt",
                "user": {"id": "supabase-user-1", "email": "a@example.com", "email_confirmed_at": "2026-01-01T00:00:00Z"},
            },
        )

    adapter = _adapter(handler)
    result = await adapter.verify_password("a@example.com", "correct-horse")

    assert result.subject == "supabase-user-1"
    assert result.email == "a@example.com"
    assert result.email_verified is True
    assert result.provider == "password"


@pytest.mark.asyncio
async def test_verify_password_sends_email_and_password_in_body() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(
            200,
            json={"access_token": "x", "user": {"id": "u1", "email": "a@example.com", "email_confirmed_at": None}},
        )

    adapter = _adapter(handler)
    await adapter.verify_password("a@example.com", "s3cret")

    import json

    parsed = json.loads(captured["body"])
    assert parsed == {"email": "a@example.com", "password": "s3cret"}


@pytest.mark.asyncio
async def test_verify_password_unverified_email_maps_to_email_verified_false() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": "x", "user": {"id": "u1", "email": "a@example.com", "email_confirmed_at": None}}
        )

    adapter = _adapter(handler)
    result = await adapter.verify_password("a@example.com", "s3cret")

    assert result.email_verified is False


@pytest.mark.asyncio
async def test_verify_password_wrong_credentials_raises_generic_invalid_credentials() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Invalid login credentials"})

    adapter = _adapter(handler)

    with pytest.raises(InvalidCredentialsError):
        await adapter.verify_password("nobody@example.com", "wrong")


@pytest.mark.asyncio
async def test_verify_federated_google_returns_authn_result_on_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["grant_type"] == "id_token"
        return httpx.Response(
            200,
            json={
                "access_token": "supabase-jwt",
                "user": {"id": "supabase-user-2", "email": "g@example.com", "email_confirmed_at": "2026-01-01T00:00:00Z"},
            },
        )

    adapter = _adapter(handler)
    result = await adapter.verify_federated("google", "raw-google-id-token")

    assert result.subject == "supabase-user-2"
    assert result.email == "g@example.com"
    assert result.email_verified is True
    assert result.provider == "google"


@pytest.mark.asyncio
async def test_verify_federated_invalid_id_token_raises_generic_invalid_credentials() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Invalid id_token"})

    adapter = _adapter(handler)

    with pytest.raises(InvalidCredentialsError):
        await adapter.verify_federated("google", "garbage-token")


@pytest.mark.asyncio
async def test_start_password_reset_posts_to_recover_endpoint() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content
        return httpx.Response(200, json={})

    adapter = _adapter(handler)
    await adapter.start_password_reset("a@example.com")

    import json

    assert captured["path"] == "/auth/v1/recover"
    assert json.loads(captured["body"]) == {"email": "a@example.com"}


@pytest.mark.asyncio
async def test_start_password_reset_does_not_raise_even_if_supabase_reports_an_error() -> None:
    """Supabase's own /recover already returns 200 regardless of whether the
    email exists (anti-enumeration, matches spec `user-authentication` ->
    "Wrong password rejected without enumeration"); this adapter does not
    add a failure mode on top of that."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate_limited"})

    adapter = _adapter(handler)
    await adapter.start_password_reset("a@example.com")  # must not raise
