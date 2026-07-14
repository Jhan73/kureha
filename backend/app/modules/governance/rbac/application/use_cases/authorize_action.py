"""`AuthorizeAction` use case (design.md §5.3): every mutating use case in
every business module starts by calling this. On denial it raises
`ActionNotPermittedError` -- the repository is never touched on a deny.

Does NOT depend on `AuditLogPort`. An earlier revision wired an inline
`rbac.denied` audit write here on the theory that governance-to-governance
imports aren't forbidden by the import-linter contracts -- but design.md
§2.4 states governance modules depend only on `shared_kernel`, never on a
peer governance module, and §10.3's own sequence diagram shows the
`rbac.denied` audit write happening in the `deny_action` PLATFORM node
(Phase 11), after this use case has already returned `rbac_ok=false` -- not
inside `AuthorizeAction` itself. Caught in PR 4's review; fixed by dropping
the dependency, matching `CheckConsent`, which never audited inline either.
"""

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
