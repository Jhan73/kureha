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
best-effort contract; matches `CalendarSyncPort`'s own docstring)."""

import hashlib
import hmac

import httpx

from app.modules.calendar.domain.calendar_credential import CalendarCredential
from app.modules.calendar.domain.calendar_event_mapping import CalendarEventMapping, CalendarSyncResult

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
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
