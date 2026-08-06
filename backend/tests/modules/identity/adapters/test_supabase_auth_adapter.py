import httpx
import pytest

from app.modules.identity.adapters.outbound.auth.supabase_auth_adapter import SupabaseAuthAdapter
from app.modules.identity.domain.errors import InvalidCredentialsError

_BASE_URL = "https://project-ref.supabase.co"
_API_KEY = "sb_publishable_test"
_SECRET_KEY = "sb_secret_test"


def _adapter(handler) -> SupabaseAuthAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SupabaseAuthAdapter(base_url=_BASE_URL, api_key=_API_KEY, http_client=client)


def _adapter_with_secret(handler) -> SupabaseAuthAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SupabaseAuthAdapter(
        base_url=_BASE_URL, api_key=_API_KEY, http_client=client, secret_key=_SECRET_KEY
    )


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
    await adapter.start_password_reset("a@example.com", redirect_to="https://app.example.com")

    import json

    assert captured["path"] == "/auth/v1/recover"
    assert json.loads(captured["body"]) == {"email": "a@example.com", "redirect_to": "https://app.example.com"}


@pytest.mark.asyncio
async def test_start_password_reset_does_not_raise_even_if_supabase_reports_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate_limited"})

    adapter = _adapter(handler)
    await adapter.start_password_reset("a@example.com", redirect_to="https://app.example.com")  # must not raise


@pytest.mark.asyncio
async def test_invite_user_posts_to_the_admin_invite_endpoint_with_secret_key_credentials() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["headers"] = request.headers
        captured["body"] = request.content
        return httpx.Response(
            200,
            json={"id": "supabase-user-invited", "email": "invitee@example.com", "email_confirmed_at": None},
        )

    adapter = _adapter_with_secret(handler)
    result = await adapter.invite_user("invitee@example.com", redirect_to="https://app.example.com/staff/login")

    import json

    assert captured["method"] == "POST"
    assert captured["path"] == "/auth/v1/invite"
    assert captured["headers"]["apikey"] == _SECRET_KEY
    assert captured["headers"]["authorization"] == f"Bearer {_SECRET_KEY}"
    assert json.loads(captured["body"]) == {
        "email": "invitee@example.com",
        "redirect_to": "https://app.example.com/staff/login",
    }
    assert result.subject == "supabase-user-invited"
    assert result.email == "invitee@example.com"
    assert result.email_verified is False
    assert result.provider == "password"


@pytest.mark.asyncio
async def test_invite_user_raises_on_a_non_2xx_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "email_exists"})

    adapter = _adapter_with_secret(handler)

    with pytest.raises(httpx.HTTPStatusError):
        await adapter.invite_user("dup@example.com", redirect_to="https://app.example.com/staff/login")


@pytest.mark.asyncio
async def test_complete_password_reset_puts_the_new_password_using_the_recovery_token_as_bearer() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["headers"] = request.headers
        captured["body"] = request.content
        return httpx.Response(
            200,
            json={"id": "supabase-user-reset", "email": "reset@example.com", "email_confirmed_at": "2026-01-01T00:00:00Z"},
        )

    adapter = _adapter(handler)
    result = await adapter.complete_password_reset("raw-recovery-token", "new-correct-horse")

    import json

    assert captured["method"] == "PUT"
    assert captured["path"] == "/auth/v1/user"
    assert captured["headers"]["apikey"] == _API_KEY
    assert captured["headers"]["authorization"] == "Bearer raw-recovery-token"
    assert json.loads(captured["body"]) == {"password": "new-correct-horse"}
    assert result.subject == "supabase-user-reset"
    assert result.email == "reset@example.com"
    assert result.email_verified is True
    assert result.provider == "password"


@pytest.mark.asyncio
async def test_complete_password_reset_invalid_or_expired_token_raises_generic_invalid_credentials() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_token"})

    adapter = _adapter(handler)

    with pytest.raises(InvalidCredentialsError):
        await adapter.complete_password_reset("expired-token", "new-password")
