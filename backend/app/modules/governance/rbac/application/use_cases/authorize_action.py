from app.modules.governance.rbac.application.ports.driven.authorization import AuthorizationPort
from app.modules.governance.rbac.domain.permission import ActionKey
from app.shared_kernel.errors import NotAuthorizedError
from app.shared_kernel.tenant_context import TenantContext


class ActionNotPermittedError(NotAuthorizedError):
    def __init__(self, action: ActionKey) -> None:
        self.action = action
        super().__init__(f"Action not permitted: {action}")


class AuthorizeAction:
    def __init__(self, authorization: AuthorizationPort) -> None:
        self._authorization = authorization

    async def execute(self, ctx: TenantContext, *, action: ActionKey) -> None:
        if await self._authorization.is_allowed(ctx, action):
            return
        raise ActionNotPermittedError(action)
