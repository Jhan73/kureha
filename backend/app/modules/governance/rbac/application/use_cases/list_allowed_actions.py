from app.modules.governance.rbac.application.ports.driven.authorization import AuthorizationPort
from app.modules.governance.rbac.domain.permission import ActionKey
from app.shared_kernel.tenant_context import TenantContext


class ListAllowedActions:
    def __init__(self, authorization: AuthorizationPort) -> None:
        self._authorization = authorization

    async def execute(self, ctx: TenantContext) -> set[ActionKey]:
        return await self._authorization.list_allowed_actions(ctx)
