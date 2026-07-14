"""`RevokeAllSessionsForUser` use case (design.md §17.4, tasks.md task 4.5,
spec `session-management` -> "Admin revokes a session"): revokes every
`user_sessions` row for a target user, scoped to the acting admin's tenant,
without touching any other user's sessions.

RBAC-gated via `AuthorizeAction` (design.md §5.3: "cada mutating use case...
comienza con authorize(ctx, action)") -- unlike `Logout` (self-service, no
gate needed), this acts on ANOTHER user's sessions, so it is a privileged
action behind the `session:revoke_all` action key."""

from app.modules.governance.rbac.application.use_cases.authorize_action import AuthorizeAction
from app.modules.identity.application.ports.driven.session_store import SessionStorePort
from app.shared_kernel.clock import ClockPort
from app.shared_kernel.tenant_context import TenantContext

_ACTION = "session:revoke_all"


class RevokeAllSessionsForUser:
    def __init__(self, authorize: AuthorizeAction, session_store: SessionStorePort, clock: ClockPort) -> None:
        self._authorize = authorize
        self._session_store = session_store
        self._clock = clock

    async def execute(self, ctx: TenantContext, *, target_user_id: str) -> int:
        await self._authorize.execute(ctx, action=_ACTION)
        return await self._session_store.revoke_all_for_user(
            ctx.tenant_id, target_user_id, revoked_at=self._clock.now()
        )
