from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.governance.rbac.adapters.outbound.rbac.action_catalog import seed_action_catalog
from app.modules.governance.rbac.adapters.outbound.rbac.default_role_permissions import (
    seed_default_role_permissions,
)


class DefaultRolePermissionsSeeder:
    """Delegates to governance's RBAC seeding functions (adapter -> adapter;
    `tenancy` may depend on `governance` per import-linter's layering
    contract). Idempotent, same as the functions it wraps."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def seed_for_tenant(self, tenant_id: str) -> None:
        await seed_action_catalog(self._conn)
        await seed_default_role_permissions(self._conn, tenant_id)
