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
