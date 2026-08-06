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
            # Idempotent retry: prior attempt already accepted this id.
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
        """Exchange OAuth code for refresh token + account email via userinfo."""
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
        """Anti-CSRF state: hmac_sha256(user_id + nonce, server_secret)."""
        message = f"{user_id}{nonce}".encode("utf-8")
        return hmac.new(server_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()

    @staticmethod
    def verify_oauth_state(*, user_id: str, nonce: str, server_secret: str, received_state: str) -> bool:
        if not received_state:
            return False
        expected = GoogleCalendarAdapter.generate_oauth_state(user_id=user_id, nonce=nonce, server_secret=server_secret)
        return hmac.compare_digest(expected, received_state)
