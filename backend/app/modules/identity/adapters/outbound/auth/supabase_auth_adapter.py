"""`SupabaseAuthAdapter`: `AuthPort` impl over Supabase Auth (GoTrue)'s REST
API (design.md §17.2, ADR-14). Standalone consumption only -- Kureha's own
DB never migrates to Supabase; this adapter is the ONLY thing in the system
that talks to the Supabase API (login/refresh-credential/reset/federated
callback), matching the hard boundary design.md draws between this and
`CalendarSyncPort`'s completely separate Google OAuth integration (never
touch/reuse anything from that module here).

Any non-2xx response from `/auth/v1/token` (wrong password, invalid/expired
`id_token`, unknown email) maps to the SAME `InvalidCredentialsError`
regardless of Supabase's specific error body -- spec `user-authentication`
-> "Wrong password rejected without enumeration": callers of `AuthPort`
must never be able to distinguish failure causes."""

from typing import Literal

import httpx

from app.modules.identity.domain.authn_result import AuthnResult
from app.modules.identity.domain.errors import InvalidCredentialsError

_TOKEN_PATH = "/auth/v1/token"
_RECOVER_PATH = "/auth/v1/recover"


class SupabaseAuthAdapter:
    def __init__(self, *, base_url: str, api_key: str, http_client: httpx.AsyncClient) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._http = http_client

    async def verify_password(self, email: str, password: str) -> AuthnResult:
        response = await self._http.post(
            f"{self._base_url}{_TOKEN_PATH}",
            params={"grant_type": "password"},
            headers=self._headers(),
            json={"email": email, "password": password},
        )
        if response.status_code >= 400:
            raise InvalidCredentialsError()
        return self._to_authn_result(response.json(), provider="password")

    async def verify_federated(self, provider: Literal["google"], id_token: str) -> AuthnResult:
        response = await self._http.post(
            f"{self._base_url}{_TOKEN_PATH}",
            params={"grant_type": "id_token"},
            headers=self._headers(),
            json={"provider": provider, "id_token": id_token},
        )
        if response.status_code >= 400:
            raise InvalidCredentialsError()
        return self._to_authn_result(response.json(), provider=provider)

    async def start_password_reset(self, email: str) -> None:
        # Supabase's own /recover already returns 200 regardless of whether
        # the email exists (anti-enumeration) -- this adapter does not add a
        # failure mode on top of that; any transport-level error is left to
        # propagate to the caller rather than being swallowed silently.
        await self._http.post(
            f"{self._base_url}{_RECOVER_PATH}",
            headers=self._headers(),
            json={"email": email},
        )

    def _headers(self) -> dict[str, str]:
        return {"apikey": self._api_key, "Content-Type": "application/json"}

    @staticmethod
    def _to_authn_result(payload: dict, *, provider: Literal["password", "google"]) -> AuthnResult:
        user = payload["user"]
        return AuthnResult(
            subject=user["id"],
            email=user["email"],
            email_verified=user.get("email_confirmed_at") is not None,
            provider=provider,
        )
