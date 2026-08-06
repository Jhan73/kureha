import uuid

import httpx

from app.main import app
from app.platform.inbound.api.access_control.dependencies import get_http_client
from app.platform.inbound.api.routers.auth import PasswordResetRequest, request_password_reset
from tests.platform.inbound.api.routers.conftest import (
    _run,
    reset_auth_ip_rate_limit_budget,
    seed_reception_actor,
)


class _RecordingHttpClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def post(self, url, *, params=None, headers=None, json=None):
        self.calls.append({"url": url, "json": json})

        class _Resp:
            status_code = 200

            def json(self_inner):
                return {}

        return _Resp()


def test_password_reset_request_always_returns_success_regardless_of_whether_the_email_exists() -> None:
    http_client = _RecordingHttpClient()

    async def _body() -> None:
        await request_password_reset(
            PasswordResetRequest(tenant_id="t1", email="existing@example.com"), http_client=http_client
        )
        await request_password_reset(
            PasswordResetRequest(tenant_id="t1", email="never-registered@example.com"), http_client=http_client
        )

    _run(_body())  # must not raise for either email

    assert [call["json"]["email"] for call in http_client.calls] == [
        "existing@example.com",
        "never-registered@example.com",
    ]


def test_password_reset_confirm_with_a_valid_token_mints_working_tokens(client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == "/auth/v1/user"
        return httpx.Response(
            200,
            json={
                "id": "supabase-reset-sub-1",
                "email": "reset-confirm-valid@example.com",
                "email_confirmed_at": "2026-01-01T00:00:00Z",
            },
        )

    actor = seed_reception_actor(email="reset-confirm-valid@example.com")

    reset_auth_ip_rate_limit_budget()
    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        base_url="https://fake-supabase.test", transport=httpx.MockTransport(handler)
    )
    try:
        response = client.post(
            "/auth/password-reset/confirm",
            json={
                "tenant_id": actor["tenant_id"],
                "recovery_token": "valid-recovery-token",
                "new_password": "new-correct-horse",
            },
        )
    finally:
        app.dependency_overrides.pop(get_http_client, None)

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == actor["user_id"]
    assert body["role"] == "reception"
    assert body["access_token"]
    assert body["refresh_token"]


def test_password_reset_request_returns_204_over_real_http_for_an_existing_and_a_nonexistent_email(client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    actor = seed_reception_actor(email="reset-request-real-http@example.com")

    reset_auth_ip_rate_limit_budget()
    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        base_url="https://fake-supabase.test", transport=httpx.MockTransport(handler)
    )
    try:
        existing_response = client.post(
            "/auth/password-reset/request",
            json={"tenant_id": actor["tenant_id"], "email": actor["email"]},
        )
        nonexistent_response = client.post(
            "/auth/password-reset/request",
            json={"tenant_id": actor["tenant_id"], "email": "never-registered-real-http@example.com"},
        )
    finally:
        app.dependency_overrides.pop(get_http_client, None)

    assert existing_response.status_code == 204
    assert nonexistent_response.status_code == 204


def test_password_reset_confirm_with_an_unseeded_tenant_id_denies_cleanly_without_a_500(client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "supabase-sub-unseeded-tenant",
                "email": "unseeded-tenant-reset@example.com",
                "email_confirmed_at": "2026-01-01T00:00:00Z",
            },
        )

    unseeded_tenant_id = str(uuid.uuid4())

    reset_auth_ip_rate_limit_budget()
    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        base_url="https://fake-supabase.test", transport=httpx.MockTransport(handler)
    )
    try:
        response = client.post(
            "/auth/password-reset/confirm",
            json={
                "tenant_id": unseeded_tenant_id,
                "recovery_token": "valid-shaped-recovery-token",
                "new_password": "new-correct-horse",
            },
        )
    finally:
        app.dependency_overrides.pop(get_http_client, None)

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth_required"
