"""`AuthPort` (design.md §17.1): mirrors `CalendarSyncPort`'s shape -- a
driven port isolating the identity module's domain/use cases from the IdP
vendor (Supabase Auth/GoTrue, ADR-14). Implemented in MVP by
`SupabaseAuthAdapter` (adapters/outbound/auth/supabase_auth_adapter.py).

Raises `app.modules.identity.domain.errors.InvalidCredentialsError` on any
verification failure -- both methods, regardless of cause (bad password,
unknown email, expired/invalid id_token), so callers never learn *why* it
failed (spec `user-authentication` -> "Wrong password rejected without
enumeration").

`invite_user`/`complete_password_reset` (added this session, staff-invite /
password-reset batch): the invite-based staff onboarding decision (design.md
§17 extension -- new staff accounts are provisioned by admin/reception
INVITING an email, never by an admin setting/seeing a temporary password) and
the "forgot password" flow share the SAME underlying Supabase mechanism (a
one-shot recovery/invite access token that lets the holder call GoTrue's
`PUT /auth/v1/user` to set a password) -- so `complete_password_reset` is the
ONE completion endpoint both flows call, deliberately not two competing
"confirm" methods.

`redirect_to` (added this session, gap-closure fix): both `invite_user` and
`start_password_reset` now take it as a REQUIRED parameter rather than
omitting it -- omitting it left the email link's destination as an implicit,
Dashboard-only "Site URL" fallback (see `SupabaseAuthAdapter`'s own
docstring, and `docs/supabase-setup.md` §6, for the gap this closes). Callers
resolve the actual URL from `Settings.frontend_base_url`
(`composition_root.py`'s `build_provision_staff_identity`/
`build_request_password_reset`), never hardcode it here."""

from typing import Literal, Protocol

from app.modules.identity.domain.authn_result import AuthnResult


class AuthPort(Protocol):
    async def verify_password(self, email: str, password: str) -> AuthnResult: ...

    async def verify_federated(self, provider: Literal["google"], id_token: str) -> AuthnResult: ...

    async def start_password_reset(self, email: str, redirect_to: str) -> None: ...

    async def invite_user(self, email: str, redirect_to: str) -> AuthnResult:
        """Admin-privileged: creates a new Supabase user server-side with NO
        password set and triggers Supabase's own invite email (the new staff
        member sets their password via `complete_password_reset` below, from
        the link in that email). Requires the SERVICE ROLE credential, never
        the anon key -- see `SupabaseAuthAdapter`'s own docstring for the
        constructor shape this implies."""
        ...

    async def complete_password_reset(self, recovery_token: str, new_password: str) -> AuthnResult:
        """Exchanges a Supabase recovery/invite access token for setting a
        new password, returning the resulting identity. The SAME completion
        step for BOTH: (1) a newly-invited staff member's first "set your
        password" screen, and (2) an existing user's "forgot password" flow
        -- both present a Supabase-issued recovery/invite token, and
        Supabase's own API treats them identically (see this port's own
        module docstring)."""
        ...
