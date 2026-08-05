"""`SupabaseAuthAdapter`: `AuthPort` impl over Supabase Auth (GoTrue)'s REST
API (design.md §17.2, ADR-14). Standalone consumption only -- Kureha's own
DB never migrates to Supabase; this adapter is the ONLY thing in the system
that talks to the Supabase API (login/refresh-credential/reset/federated
callback/invite), matching the hard boundary design.md draws between this
and `CalendarSyncPort`'s completely separate Google OAuth integration (never
touch/reuse anything from that module here).

Any non-2xx response from `/auth/v1/token` (wrong password, invalid/expired
`id_token`, unknown email) maps to the SAME `InvalidCredentialsError`
regardless of Supabase's specific error body -- spec `user-authentication`
-> "Wrong password rejected without enumeration": callers of `AuthPort`
must never be able to distinguish failure causes.

**`invite_user`/`complete_password_reset` (staff-invite / password-reset
batch), UNVERIFIED against a real Supabase project -- flagged, not silently
assumed, per this codebase's own established convention (see
`PostgresUserDirectory.provision_patient_user`'s docstring for the pattern
this follows).** This dev environment has no reachable Supabase project
(ADR-14: standalone project), so these two request/response shapes are the
most standard, well-documented GoTrue Admin API shapes available, not
empirically confirmed:

- `invite_user`: `POST /auth/v1/invite`, body `{"email": ..., "redirect_to":
  ...}`, authenticated with the SERVICE ROLE key on BOTH `apikey` and
  `Authorization: Bearer` (an admin-privileged call -- GoTrue authorizes
  admin endpoints off the `Authorization` bearer's own role claim, not
  `apikey` alone). Assumed response: the created Supabase user object at the
  TOP LEVEL (no `{"user": ...}` wrapper) -- GoTrue's admin endpoints return
  the bare `User` object, unlike `/auth/v1/token`'s wrapped shape
  `_to_authn_result` below parses.
- `complete_password_reset`: `PUT /auth/v1/user`, body `{"password": ...}`,
  authenticated with the caller's own RECOVERY/INVITE access token as
  `Authorization: Bearer` (proving "I am this user", the same way any
  already-authenticated GoTrue call works) and the ANON key on `apikey`
  (never service-role -- the caller acts as themselves, not as an admin).
  Assumed response: same bare `User` object shape as `invite_user`.

**`redirect_to` (added this session, gap-closure fix -- see
`docs/supabase-setup.md` §6): `invite_user` and `start_password_reset` now
send it as a top-level `redirect_to` JSON body field**, matching the ONE
shape GoTrue's admin `/admin/generate_link` endpoint documents explicitly
(`redirect_to: string` in its OpenAPI spec) and the field name every
`supabase-js` helper that wraps `/invite`/`/recover` exposes as
`redirectTo` -- the closest verified precedent available, but like every
other shape in this file, NOT empirically confirmed against a real project
for these two specific endpoints. Before this fix, neither call sent
`redirect_to` at all, so the email link silently fell back to whatever "Site
URL" happened to be configured in the Supabase Dashboard -- an implicit,
per-environment, easy-to-forget dependency instead of an explicit,
`Settings`-driven one.

**Whoever ships this to a real Supabase project MUST smoke-test both calls
against it before relying on them in production** -- a wrong assumption here
(e.g. Supabase actually wraps the admin response in `{"user": ...}` too, or
uses a different admin-invite path) will surface as either an unhandled
`KeyError` parsing the response or a silently-wrong header, not caught by
this file's own `httpx.MockTransport`-based tests (which assert against
these SAME assumed shapes, so they cannot catch a wrong assumption --
only a real integration/smoke test can)."""

from typing import Literal

import httpx

from app.modules.identity.domain.authn_result import AuthnResult
from app.modules.identity.domain.errors import InvalidCredentialsError

_TOKEN_PATH = "/auth/v1/token"
_RECOVER_PATH = "/auth/v1/recover"
_INVITE_PATH = "/auth/v1/invite"
_USER_PATH = "/auth/v1/user"


class SupabaseAuthAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        http_client: httpx.AsyncClient,
        service_role_key: str | None = None,
    ) -> None:
        """`service_role_key` (optional, added this session): a SEPARATE,
        more-privileged credential from `api_key` (the anon key), needed
        only by `invite_user` -- a single-adapter-instance-with-an-extra-
        constructor-param design, chosen over standing up a second adapter
        class, since every OTHER method here (`verify_password`,
        `verify_federated`, `start_password_reset`,
        `complete_password_reset`) is unaffected and correctly keeps using
        the anon `api_key`; a second class would duplicate `_base_url`/
        `_http` wiring and the `_to_authn_result` parsing helper for no
        isolation benefit (this adapter is already the ONLY thing in the
        system talking to Supabase, per this module's own docstring, so
        there is no cross-cutting boundary a second class would enforce).
        `None` by default so every EXISTING caller (`build_login`/
        `build_refresh_token` in `composition_root.py`, which never invite)
        keeps working unchanged; `invite_user` raises `RuntimeError` if
        called without one configured, a startup-misconfiguration signal,
        not a domain error worth mapping into the `errors.py` §21 envelope."""
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._service_role_key = service_role_key
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

    async def start_password_reset(self, email: str, redirect_to: str) -> None:
        # Supabase's own /recover already returns 200 regardless of whether
        # the email exists (anti-enumeration) -- this adapter does not add a
        # failure mode on top of that; any transport-level error is left to
        # propagate to the caller rather than being swallowed silently.
        await self._http.post(
            f"{self._base_url}{_RECOVER_PATH}",
            headers=self._headers(),
            json={"email": email, "redirect_to": redirect_to},
        )

    async def invite_user(self, email: str, redirect_to: str) -> AuthnResult:
        if not self._service_role_key:
            # Startup misconfiguration, not a domain error -- see
            # constructor's own docstring. Falls through to the generic 500
            # `internal_error` envelope (errors.py's catch-all), same as any
            # other unmapped exception.
            raise RuntimeError(
                "SupabaseAuthAdapter.invite_user requires service_role_key, none was configured"
            )
        response = await self._http.post(
            f"{self._base_url}{_INVITE_PATH}",
            headers=self._admin_headers(),
            json={"email": email, "redirect_to": redirect_to},
        )
        # Deliberately NOT `InvalidCredentialsError` -- see module docstring:
        # a failed admin-triggered invite is a genuine infra/config problem,
        # not an authn attempt whose failure reason must be hidden from an
        # attacker. `raise_for_status()` propagates `httpx.HTTPStatusError`,
        # which falls through to the generic 500 envelope.
        response.raise_for_status()
        return self._to_authn_result_bare(response.json(), provider="password")

    async def complete_password_reset(self, recovery_token: str, new_password: str) -> AuthnResult:
        response = await self._http.put(
            f"{self._base_url}{_USER_PATH}",
            headers=self._recovery_headers(recovery_token),
            json={"password": new_password},
        )
        if response.status_code >= 400:
            # Same generic-failure convention as verify_password/
            # verify_federated -- an invalid/expired recovery or invite
            # token maps to the SAME `InvalidCredentialsError`, chosen over
            # inventing a new error type (this port's own docstring: "your
            # call, document it" -- documented here).
            raise InvalidCredentialsError()
        return self._to_authn_result_bare(response.json(), provider="password")

    def _headers(self) -> dict[str, str]:
        return {"apikey": self._api_key, "Content-Type": "application/json"}

    def _admin_headers(self) -> dict[str, str]:
        return {
            "apikey": self._service_role_key,
            "Authorization": f"Bearer {self._service_role_key}",
            "Content-Type": "application/json",
        }

    def _recovery_headers(self, recovery_token: str) -> dict[str, str]:
        return {
            "apikey": self._api_key,
            "Authorization": f"Bearer {recovery_token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _to_authn_result(payload: dict, *, provider: Literal["password", "google"]) -> AuthnResult:
        user = payload["user"]
        return AuthnResult(
            subject=user["id"],
            email=user["email"],
            email_verified=user.get("email_confirmed_at") is not None,
            provider=provider,
        )

    @staticmethod
    def _to_authn_result_bare(user: dict, *, provider: Literal["password", "google"]) -> AuthnResult:
        """Same parsing as `_to_authn_result` above but for GoTrue admin
        endpoints' assumed bare-`User`-object response shape (no `{"user":
        ...}` wrapper) -- see this module's own docstring for the flagged,
        unverified assumption."""
        return AuthnResult(
            subject=user["id"],
            email=user["email"],
            email_verified=user.get("email_confirmed_at") is not None,
            provider=provider,
        )
