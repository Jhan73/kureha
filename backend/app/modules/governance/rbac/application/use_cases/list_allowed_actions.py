"""`ListAllowedActions` use case (design.md §5.4): thin delegation to
`AuthorizationPort` -- feeds `resolve_toolset`'s `allowed_actions` (tasks.md
Phase 11), which builds the copilot's dynamic toolset so a denied action is
never even offered as a tool."""

from app.modules.governance.rbac.application.ports.driven.authorization import AuthorizationPort
from app.modules.governance.rbac.domain.permission import ActionKey
from app.shared_kernel.tenant_context import TenantContext


class ListAllowedActions:
    def __init__(self, authorization: AuthorizationPort) -> None:
        self._authorization = authorization

    async def execute(self, ctx: TenantContext) -> set[ActionKey]:
        return await self._authorization.list_allowed_actions(ctx)
