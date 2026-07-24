"""`GoogleCalendarAdapter`: `CalendarSyncPort` impl over Google Calendar API
v3's REST surface (design.md §7.1/§7.3/§7.6, tasks.md task 9.3). Uses
`httpx.AsyncClient` directly against Google's REST endpoints (not the
blocking `google-api-python-client`), matching `SupabaseAuthAdapter`'s
async-native external-HTTP-adapter shape (identity module precedent) --
`client_id`/`client_secret`/`http_client` are constructor-injected, never
read from `app.config.settings` inside this class.

**PATCH-first upsert semantics (design.md §7.6):** `upsert_event` tries
`events.patch` on `mapping.idempotency_key` FIRST -- if the event already
exists (a reschedule, or a retry of an earlier successful create), this
both finds it AND applies the current start/end/summary in one call. Only a
`404` (event genuinely does not exist yet) falls back to `events.insert`
with that same fixed id. A `409` on THAT insert means a prior attempt's
insert already landed (the exact "timeout right after Google accepted the
insert" scenario ADR-18 names) -- treated as success, not an error, because
the id is derived purely from `appointment_id` (design.md §7.6): whichever
attempt actually wrote the row, the content is the one this same
idempotency key was always going to carry.

**`delete_event`** treats `404`/`410` (already gone) as an idempotent
success, same reasoning as `upsert_event`'s `409` case.

**Never raises for a Google-side failure** -- every branch returns
`CalendarSyncResult(ok=False, error=...)` instead (design.md §7.2's
best-effort contract; matches `CalendarSyncPort`'s own docstring).

**`exchange_authorization_code` (added tasks.md task 10.1, routers):** the
one method on this class that does NOT follow the "never raises" contract
above -- it belongs to the OAuth2 AUTHORIZATION leg (the callback route,
BEFORE any `CalendarCredential`/refresh_token exists yet), not the
`CalendarSyncPort` best-effort contract `upsert_event`/`delete_event` follow.
Flagged, not silently invented: no call site anywhere in this codebase
exchanged an authorization `code` for tokens before task 10.1 -- every other
method here starts from an ALREADY-issued refresh token. Raises
`CalendarOAuthExchangeError` (a `ValidationError` subclass, maps to a 422
via `platform/inbound/api/errors.py`) on any non-2xx response, so the
callback route can let it propagate through the central exception handler
rather than hand-rolling its own error response."""

import hashlib
import hmac

import httpx

from app.modules.calendar.domain.calendar_credential import CalendarCredential
from app.modules.calendar.domain.calendar_event_mapping import CalendarEventMapping, CalendarSyncResult
from app.modules.calendar.domain.errors import CalendarOAuthExchangeError
from app.modules.calendar.domain.oauth_exchange import AuthorizationCodeExchange

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
_IDEMPOTENT_DELETE_STATUSES = (200, 204, 404, 410)


class GoogleCalendarAdapter:
    def __init__(self, *, client_id: str, client_secret: str, http_client: httpx.AsyncClient) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http_client

    async def upsert_event(self, cred: CalendarCredential, mapping: CalendarEventMapping) -> CalendarSyncResult:
        try:
            access_token = await self._exchange_refresh_token(cred.refresh_token)
        except Exception as exc:  # noqa: BLE001 -- best-effort port, see module docstring
            return CalendarSyncResult(ok=False, error=f"token exchange failed: {exc}")

        body = self._to_event_body(mapping)
        headers = self._auth_headers(access_token)

        try:
            patch_response = await self._http.patch(
                f"{_EVENTS_URL}/{mapping.idempotency_key}", headers=headers, json=body
            )
        except Exception as exc:  # noqa: BLE001
            return CalendarSyncResult(ok=False, error=f"patch request failed: {exc}")

        if patch_response.status_code < 300:
            return CalendarSyncResult(ok=True, google_event_id=mapping.idempotency_key)
        if patch_response.status_code != 404:
            return CalendarSyncResult(ok=False, error=f"patch failed: {patch_response.status_code}")

        try:
            insert_response = await self._http.post(
                _EVENTS_URL, headers=headers, json={"id": mapping.idempotency_key, **body}
            )
        except Exception as exc:  # noqa: BLE001
            return CalendarSyncResult(ok=False, error=f"insert request failed: {exc}")

        if insert_response.status_code in (200, 201):
            return CalendarSyncResult(ok=True, google_event_id=mapping.idempotency_key)
        if insert_response.status_code == 409:
            # ADR-18: idempotent retry -- a prior attempt already accepted
            # this exact id, treat as success (see module docstring).
            return CalendarSyncResult(ok=True, google_event_id=mapping.idempotency_key)
        return CalendarSyncResult(ok=False, error=f"insert failed: {insert_response.status_code}")

    async def delete_event(self, cred: CalendarCredential, google_event_id: str) -> CalendarSyncResult:
        try:
            access_token = await self._exchange_refresh_token(cred.refresh_token)
        except Exception as exc:  # noqa: BLE001
            return CalendarSyncResult(ok=False, error=f"token exchange failed: {exc}")

        try:
            response = await self._http.delete(
                f"{_EVENTS_URL}/{google_event_id}", headers=self._auth_headers(access_token)
            )
        except Exception as exc:  # noqa: BLE001
            return CalendarSyncResult(ok=False, error=f"delete request failed: {exc}")

        if response.status_code in _IDEMPOTENT_DELETE_STATUSES:
            return CalendarSyncResult(ok=True, google_event_id=google_event_id)
        return CalendarSyncResult(ok=False, error=f"delete failed: {response.status_code}")

    async def exchange_authorization_code(self, code: str, *, redirect_uri: str) -> AuthorizationCodeExchange:
        """`grant_type=authorization_code` leg of design.md §7.3's OAuth2
        flow -- exchanges the callback's `code` for a refresh token, then
        resolves the authorized account's email via Google's `userinfo`
        endpoint (needed by `ConnectPatientCalendar`'s registered-email
        comparison, which the caller cannot get from anywhere else)."""
        try:
            response = await self._http.post(
                _TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": redirect_uri,
                },
            )
        except Exception as exc:  # noqa: BLE001 -- transport failure, not a Google-rejected code
            raise CalendarOAuthExchangeError(f"authorization code exchange request failed: {exc}") from exc

        if response.status_code >= 400:
            raise CalendarOAuthExchangeError(f"authorization code exchange rejected: {response.status_code}")

        payload = response.json()
        refresh_token = payload.get("refresh_token")
        access_token = payload.get("access_token")
        if not refresh_token or not access_token:
            # Google omits `refresh_token` on a re-consent without
            # `access_type=offline&prompt=consent` -- a genuine caller-side
            # misconfiguration of the /authorize redirect, not a transport
            # error, so it gets the same client-validation mapping.
            raise CalendarOAuthExchangeError("token response missing refresh_token/access_token")

        email = await self._fetch_userinfo_email(access_token)
        return AuthorizationCodeExchange(refresh_token=refresh_token, google_email=email, scope=payload.get("scope", ""))

    async def _fetch_userinfo_email(self, access_token: str) -> str:
        try:
            response = await self._http.get(_USERINFO_URL, headers=self._auth_headers(access_token))
        except Exception as exc:  # noqa: BLE001
            raise CalendarOAuthExchangeError(f"userinfo request failed: {exc}") from exc
        if response.status_code >= 400:
            raise CalendarOAuthExchangeError(f"userinfo request rejected: {response.status_code}")
        email = response.json().get("email")
        if not email:
            raise CalendarOAuthExchangeError("userinfo response missing email")
        return email

    async def _exchange_refresh_token(self, refresh_token: str) -> str:
        response = await self._http.post(
            _TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        if response.status_code >= 400:
            raise RuntimeError(f"status {response.status_code}")
        return response.json()["access_token"]

    @staticmethod
    def _auth_headers(access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    @staticmethod
    def _to_event_body(mapping: CalendarEventMapping) -> dict:
        return {
            "summary": mapping.summary,
            "start": {"dateTime": mapping.starts_at.isoformat()},
            "end": {"dateTime": mapping.ends_at.isoformat()},
        }

    @staticmethod
    def generate_oauth_state(*, user_id: str, nonce: str, server_secret: str) -> str:
        """design.md §7.3's anti-CSRF `state`: `hmac_sha256(user_id + nonce,
        server_secret)`. Pure/stateless -- verification (below) recomputes
        and compares, no server-side state store needed beyond whatever
        already-persisted `nonce` the caller compares against (design.md:
        "se guarda en la sesion del usuario, p.ej. via
        user_sessions.metadata" -- Phase 10 wiring, not built here)."""
        message = f"{user_id}{nonce}".encode("utf-8")
        return hmac.new(server_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()

    @staticmethod
    def verify_oauth_state(*, user_id: str, nonce: str, server_secret: str, received_state: str) -> bool:
        if not received_state:
            return False
        expected = GoogleCalendarAdapter.generate_oauth_state(user_id=user_id, nonce=nonce, server_secret=server_secret)
        return hmac.compare_digest(expected, received_state)
