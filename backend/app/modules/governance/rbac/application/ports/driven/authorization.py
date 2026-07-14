"""`AuthorizationPort` (design.md §5.3): the driven port `AuthorizeAction`/
`ListAllowedActions` depend on. Implemented in MVP by `PermissionService`
(adapters/outbound/rbac/permission_service.py), which resolves
`PermissionPolicy`'s precedence internally -- this port's contract is
already-resolved booleans/sets, so use cases never see the raw
role/user-override rows."""

from typing import Protocol

from app.modules.governance.rbac.domain.permission import ActionKey
from app.shared_kernel.tenant_context import TenantContext


class AuthorizationPort(Protocol):
    async def is_allowed(self, ctx: TenantContext, action: ActionKey) -> bool:
        """Resolves the effective permission for one action (design.md
        §5.2's precedence), live per request -- never cached cross-request
        (design.md §5.6/ADR-16)."""
        ...

    async def list_allowed_actions(self, ctx: TenantContext) -> set[ActionKey]:
        """Resolves the full set of allowed actions for the actor in one
        query (design.md §5.4) -- feeds `resolve_toolset`'s dynamic
        toolset."""
        ...
