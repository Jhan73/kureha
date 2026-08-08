from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_NIL_UUID = "00000000-0000-0000-0000-000000000000"
_GUC_COLUMNS = ("tenant_id", "site_id", "role", "user_id", "patient_id", "professional_id")


class PostgresTenantProvisioningRepository:
    """Atomically provisions a new tenant, its default site, and the first
    admin user on `conn`, run as `app_runtime` (RLS enforced, no bypass --
    design.md ADR-02). Owns the `SET LOCAL app.*` choreography this
    requires: `app.site_id` can only be set once the site row exists,
    because `users_admin_write` checks it against the inserted row.

    RBAC seeding and audit logging are NOT performed here -- callers invoke
    `RbacSeederPort`/`AuditLogPort` separately over the same connection,
    relying on `SET LOCAL`'s transaction-lifetime scope to keep the GUCs
    set here in effect for those subsequent calls.
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def provision(
        self,
        *,
        tenant_id: str,
        name: str,
        site_id: str,
        site_name: str,
        admin_user_id: str,
        admin_email: str,
    ) -> None:
        await self._set_local_context(tenant_id=tenant_id, role="admin")

        await self._conn.execute(
            text("INSERT INTO tenants (id, name) VALUES (:id, :name)"),
            {"id": tenant_id, "name": name},
        )
        await self._conn.execute(
            text("INSERT INTO sites (id, tenant_id, name) VALUES (:id, :tenant_id, :name)"),
            {"id": site_id, "tenant_id": tenant_id, "name": site_name},
        )

        await self._conn.execute(text(f"SET LOCAL app.site_id = '{site_id}'"))

        await self._conn.execute(
            text("INSERT INTO users (id, tenant_id, site_id, role) VALUES (:id, :tenant_id, :site_id, 'admin')"),
            {"id": admin_user_id, "tenant_id": tenant_id, "site_id": site_id},
        )
        await self._conn.execute(
            text(
                "INSERT INTO user_credentials (tenant_id, user_id, email, auth_subject) "
                "VALUES (:tenant_id, :user_id, :email, NULL)"
            ),
            {"tenant_id": tenant_id, "user_id": admin_user_id, "email": admin_email},
        )

    async def _set_local_context(self, *, tenant_id: str, role: str) -> None:
        """Sets all six `app.*` GUCs -- `current_setting()` without
        `missing_ok` raises if any is unset, so unused ones get a nil-UUID
        sentinel (matches `access_control/session_context.py`)."""
        values = {"tenant_id": tenant_id, "role": role}
        for column in _GUC_COLUMNS:
            value = values.get(column, _NIL_UUID)
            await self._conn.execute(text(f"SET LOCAL app.{column} = '{value}'"))
