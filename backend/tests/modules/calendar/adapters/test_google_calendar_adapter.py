"""Task 9.3: `GoogleCalendarAdapter` -- `CalendarSyncPort` impl over Google
Calendar API v3 (design.md §7.1/§7.3/§7.6). No real network: `httpx`'s
`MockTransport` stands in for Google's HTTP surface (same convention as
`test_supabase_auth_adapter.py`).

Three concerns per tasks.md task 9.3:
1. `upsert_event`/`delete_event`'s idempotent upsert semantics (PATCH-first,
   INSERT-fallback-on-404, 409-on-insert-is-success).
2. OAuth2 `state` CSRF generation/verification (pure, no network).
3. Idempotency-key derivation is covered separately in
   tests/modules/calendar/domain/test_idempotency.py -- this module only
   asserts the adapter actually USES it as the Calendar event id."""

import httpx
import pytest

from app.modules.calendar.adapters.outbound.calendar.google_calendar_adapter import GoogleCalendarAdapter
from app.modules.calendar.domain.calendar_credential import CalendarCredential
from app.modules.calendar.domain.calendar_event_mapping import CalendarEventMapping
from app.modules.calendar.domain.errors import CalendarOAuthExchangeError
from datetime import datetime, timezone

_CLIENT_ID = "test-client-id"
_CLIENT_SECRET = "test-client-secret"
_T0 = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)


def _adapter(handler) -> GoogleCalendarAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GoogleCalendarAdapter(client_id=_CLIENT_ID, client_secret=_CLIENT_SECRET, http_client=client)


def _cred() -> CalendarCredential:
    return CalendarCredential(patient_id="p1", refresh_token="rt-secret", scope="calendar.events")


def _mapping() -> CalendarEventMapping:
    return CalendarEventMapping(
        appointment_id="appt-1", idempotency_key="kurehaabc123", starts_at=_T0, ends_at=_T1, summary="Kureha appointment"
    )


def _token_response() -> httpx.Response:
    return httpx.Response(200, json={"access_token": "google-access-token", "expires_in": 3600})


async def test_upsert_event_patches_first_and_succeeds_when_the_event_already_exists() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.host == "oauth2.googleapis.com":
            return _token_response()
        assert request.method == "PATCH"
        assert request.url.path.endswith("/kurehaabc123")
        assert request.headers["Authorization"] == "Bearer google-access-token"
        return httpx.Response(200, json={"id": "kurehaabc123"})

    result = await _adapter(handler).upsert_event(_cred(), _mapping())

    assert result.ok is True
    assert result.google_event_id == "kurehaabc123"
    assert ("PATCH", "/calendar/v3/calendars/primary/events/kurehaabc123") in [(m, p) for m, p in calls]


async def test_upsert_event_falls_back_to_insert_when_patch_404s() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return _token_response()
        if request.method == "PATCH":
            return httpx.Response(404, json={"error": "not found"})
        assert request.method == "POST"
        assert request.url.path == "/calendar/v3/calendars/primary/events"
        return httpx.Response(201, json={"id": "kurehaabc123"})

    result = await _adapter(handler).upsert_event(_cred(), _mapping())

    assert result.ok is True
    assert result.google_event_id == "kurehaabc123"


async def test_upsert_event_treats_409_on_insert_as_idempotent_success() -> None:
    """ADR-18 (design.md §7.6): a retry after a timeout that Google actually
    accepted lands here -- 409 means "already exists", not an error."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return _token_response()
        if request.method == "PATCH":
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(409, json={"error": "already exists"})

    result = await _adapter(handler).upsert_event(_cred(), _mapping())

    assert result.ok is True
    assert result.google_event_id == "kurehaabc123"


async def test_upsert_event_reports_failure_without_raising_on_a_real_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return _token_response()
        if request.method == "PATCH":
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(500, json={"error": "internal"})

    result = await _adapter(handler).upsert_event(_cred(), _mapping())

    assert result.ok is False
    assert result.error is not None


async def test_upsert_event_reports_failure_when_token_exchange_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(400, json={"error": "invalid_grant"})
        raise AssertionError("must not call the Calendar API without a valid access token")

    result = await _adapter(handler).upsert_event(_cred(), _mapping())

    assert result.ok is False
    assert result.error is not None


async def test_delete_event_succeeds() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return _token_response()
        assert request.method == "DELETE"
        assert request.url.path.endswith("/kurehaabc123")
        return httpx.Response(204)

    result = await _adapter(handler).delete_event(_cred(), "kurehaabc123")

    assert result.ok is True


async def test_delete_event_missing_event_is_idempotent_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return _token_response()
        return httpx.Response(410, json={"error": "gone"})

    result = await _adapter(handler).delete_event(_cred(), "kurehaabc123")

    assert result.ok is True


def test_generate_oauth_state_is_deterministic_for_the_same_inputs() -> None:
    first = GoogleCalendarAdapter.generate_oauth_state(user_id="u1", nonce="n1", server_secret="s3cr3t")
    second = GoogleCalendarAdapter.generate_oauth_state(user_id="u1", nonce="n1", server_secret="s3cr3t")

    assert first == second


def test_generate_oauth_state_differs_across_users_or_nonces() -> None:
    base = GoogleCalendarAdapter.generate_oauth_state(user_id="u1", nonce="n1", server_secret="s3cr3t")

    assert base != GoogleCalendarAdapter.generate_oauth_state(user_id="u2", nonce="n1", server_secret="s3cr3t")
    assert base != GoogleCalendarAdapter.generate_oauth_state(user_id="u1", nonce="n2", server_secret="s3cr3t")


def test_verify_oauth_state_accepts_the_matching_state() -> None:
    state = GoogleCalendarAdapter.generate_oauth_state(user_id="u1", nonce="n1", server_secret="s3cr3t")

    assert (
        GoogleCalendarAdapter.verify_oauth_state(user_id="u1", nonce="n1", server_secret="s3cr3t", received_state=state)
        is True
    )


def test_verify_oauth_state_rejects_a_tampered_or_missing_state() -> None:
    assert (
        GoogleCalendarAdapter.verify_oauth_state(
            user_id="u1", nonce="n1", server_secret="s3cr3t", received_state="garbage"
        )
        is False
    )
    assert (
        GoogleCalendarAdapter.verify_oauth_state(user_id="u1", nonce="n1", server_secret="s3cr3t", received_state="")
        is False
    )


async def test_exchange_authorization_code_returns_refresh_token_and_email() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            assert "code=auth-code-1" in request.content.decode()
            assert "grant_type=authorization_code" in request.content.decode()
            return httpx.Response(
                200, json={"access_token": "google-access-token", "refresh_token": "google-refresh-token", "scope": "calendar.events"}
            )
        assert request.url.path == "/oauth2/v3/userinfo"
        assert request.headers["Authorization"] == "Bearer google-access-token"
        return httpx.Response(200, json={"email": "patient@example.com"})

    result = await _adapter(handler).exchange_authorization_code(
        "auth-code-1", redirect_uri="https://kureha.example/calendar/oauth/callback"
    )

    assert result.refresh_token == "google-refresh-token"
    assert result.google_email == "patient@example.com"
    assert result.scope == "calendar.events"


async def test_exchange_authorization_code_raises_on_a_rejected_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    with pytest.raises(CalendarOAuthExchangeError):
        await _adapter(handler).exchange_authorization_code("bad-code", redirect_uri="https://kureha.example/callback")


async def test_exchange_authorization_code_raises_when_refresh_token_is_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "google-access-token"})
        return httpx.Response(200, json={"email": "patient@example.com"})

    with pytest.raises(CalendarOAuthExchangeError):
        await _adapter(handler).exchange_authorization_code("auth-code-1", redirect_uri="https://kureha.example/callback")
