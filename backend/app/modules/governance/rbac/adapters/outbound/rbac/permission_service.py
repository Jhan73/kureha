from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.governance.rbac.domain.permission import ActionKey, PermissionPolicy
from app.shared_kernel.tenant_context import TenantContext

_MemoKey = tuple[str, str, str | None, ActionKey]


class PermissionService:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn
        self._memo: dict[_MemoKey, bool] = {}

    async def is_allowed(self, ctx: TenantContext, action: ActionKey) -> bool:
        key: _MemoKey = (ctx.tenant_id, ctx.role, ctx.actor_id, action)
        if key in self._memo:
            return self._memo[key]

        role_grant, user_override = await self._grants(ctx.tenant_id, ctx.role, ctx.actor_id, action)
        resolved = PermissionPolicy.resolve(user_override=user_override, role_grant=role_grant)
        self._memo[key] = resolved
        return resolved

    async def list_allowed_actions(self, ctx: TenantContext) -> set[ActionKey]:
        """Resolve all catalog actions once; warms request-scoped memo."""
        result = await self._conn.execute(
            text(
                """
                SELECT ap.key AS action,
                       up.allowed AS user_override,
                       rp.allowed AS role_grant
                FROM action_permissions ap
                LEFT JOIN role_permissions rp
                  ON rp.tenant_id = :tenant_id AND rp.role = :role AND rp.action = ap.key
                LEFT JOIN user_permissions up
                  ON up.tenant_id = :tenant_id AND up.user_id = :user_id AND up.action = ap.key
                """
            ),
            {"tenant_id": ctx.tenant_id, "role": ctx.role, "user_id": ctx.actor_id},
        )
        allowed: set[ActionKey] = set()
        for row in result:
            resolved = PermissionPolicy.resolve(user_override=row.user_override, role_grant=row.role_grant)
            self._memo[(ctx.tenant_id, ctx.role, ctx.actor_id, row.action)] = resolved
            if resolved:
                allowed.add(row.action)
        return allowed

    async def _grants(
        self, tenant_id: str, role: str, user_id: str | None, action: ActionKey
    ) -> tuple[bool | None, bool | None]:
        """Single round trip resolving both the role grant and (if an actor
        is present) the user override -- same LEFT JOIN shape as
        `list_allowed_actions`, narrowed to one action."""
        result = await self._conn.execute(
            text(
                """
                SELECT rp.allowed AS role_grant, up.allowed AS user_override
                FROM action_permissions ap
                LEFT JOIN role_permissions rp
                  ON rp.tenant_id = :tenant_id AND rp.role = :role AND rp.action = ap.key
                LEFT JOIN user_permissions up
                  ON up.tenant_id = :tenant_id AND up.user_id = :user_id AND up.action = ap.key
                WHERE ap.key = :action
                """
            ),
            {"tenant_id": tenant_id, "role": role, "user_id": user_id, "action": action},
        )
        row = result.first()
        if row is None:
            return None, None
        return row.role_grant, row.user_override
