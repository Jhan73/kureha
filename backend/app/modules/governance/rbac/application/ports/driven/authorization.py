from typing import Protocol

from app.modules.governance.rbac.domain.permission import ActionKey
from app.shared_kernel.tenant_context import TenantContext


class AuthorizationPort(Protocol):
    async def is_allowed(self, ctx: TenantContext, action: ActionKey) -> bool:
        """Effective permission for one action; never cached cross-request."""
        ...

    async def list_allowed_actions(self, ctx: TenantContext) -> set[ActionKey]:
        """Full allowed set in one query (e.g. dynamic toolset)."""
        ...
