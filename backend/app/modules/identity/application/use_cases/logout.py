"""`Logout` use case (design.md §17.4, tasks.md task 4.5, spec
`session-management` -> "User logs out"): revokes the caller's own session.
Self-service -- not RBAC-gated (logging yourself out is not a privileged
action; contrast with `RevokeAllSessionsForUser`, the admin equivalent,
which does go through `AuthorizeAction`).

Takes a raw `refresh_token: str`, NOT a `session_id` (fix, confirmed review
finding): nothing in this module ever hands a client a `user_sessions.id`
-- `Login`/`RefreshToken` only ever return an opaque refresh token string, so
a `session_id`-based signature described an id no real caller could ever
have. Hashes the presented token and looks the session up via
`SessionStorePort.find_by_hash`, mirroring `RefreshToken.execute` exactly
(same hashing helper, same lookup port method)."""

from app.modules.identity.application.ports.driven.session_store import SessionStorePort
from app.modules.identity.domain.errors import SessionNotFoundError
from app.modules.identity.domain.refresh_token_hash import hash_refresh_token
from app.shared_kernel.clock import ClockPort
from app.shared_kernel.tenant_context import TenantContext


class Logout:
    def __init__(self, session_store: SessionStorePort, clock: ClockPort) -> None:
        self._session_store = session_store
        self._clock = clock

    async def execute(self, ctx: TenantContext, *, refresh_token: str) -> None:
        session = await self._session_store.find_by_hash(hash_refresh_token(refresh_token))
        if (
            session is None
            or session.tenant_id != ctx.tenant_id
            or session.user_id != ctx.actor_id
        ):
            # Same error whether the token does not match any session at
            # all or matches one belonging to another user/tenant -- see
            # SessionNotFoundError's docstring.
            raise SessionNotFoundError()

        await self._session_store.revoke(session.id, revoked_at=self._clock.now())
