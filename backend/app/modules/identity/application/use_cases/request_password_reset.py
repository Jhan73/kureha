"""`RequestPasswordReset` use case (design.md §17 extension, password-reset
batch): a thin wrapper over `AuthPort.start_password_reset`, kept as its own
use case -- rather than `routers/auth.py` touching `SupabaseAuthAdapter`
directly -- for consistency with every other `/auth/*` route (`Login`/
`RefreshToken`/`Logout` are all real use cases, never a bare adapter call
from a router handler).

No tenant-scoped lookup, no audit write: `AuthPort.start_password_reset`
already returns success unconditionally regardless of whether the email
exists (Supabase's own anti-enumeration behavior, see
`SupabaseAuthAdapter.start_password_reset`'s own docstring) -- there is
nothing this use case could meaningfully gate or record without either
defeating that anti-enumeration property (e.g. auditing "email not found")
or adding a distinction the caller could observe. `PasswordResetRequest`'s
`tenant_id` field (`routers/auth.py`) is therefore accepted for shape
symmetry with `LoginRequest` but never reaches this use case at all.

`redirect_url` (added this session, gap-closure fix -- see
`docs/supabase-setup.md` §6): this request is never tenant/role-scoped (no
`users` lookup happens here at all, see above), so there is no signal to
tell a patient's reset apart from a staff member's -- both share this one
use case. Without a way to know which role's login page to send the user
back to, this deliberately targets the bare frontend origin
(`Settings.frontend_base_url`, `composition_root.py`'s
`build_request_password_reset`) rather than guessing `/login` vs
`/staff/login`. Flagged, not silently invented: neither a dedicated
password-reset-confirm page nor a role-aware redirect exists yet on the
frontend -- a future task should add one and pass a more specific URL here."""

from app.modules.identity.application.ports.driven.auth import AuthPort


class RequestPasswordReset:
    def __init__(self, auth: AuthPort, redirect_url: str) -> None:
        self._auth = auth
        self._redirect_url = redirect_url

    async def execute(self, email: str) -> None:
        await self._auth.start_password_reset(email, redirect_to=self._redirect_url)
