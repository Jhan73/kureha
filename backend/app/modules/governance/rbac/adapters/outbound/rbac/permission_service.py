"""`PermissionService`: `AuthorizationPort` adapter reading
`action_permissions`/`role_permissions`/`user_permissions` (design.md
§4.4/§5.6, ADR-16).

**Request-scoped memo only -- no cross-request cache.** The `_memo` dict
below lives on the instance, not anywhere shared -- it is only safe because
the composition root (tasks.md task 10.2, not yet built) MUST construct a
fresh `PermissionService` per request, same as every other adapter that
takes a request-scoped `AsyncConnection`. Never make this a singleton,
never store it on `app.state`, never reuse one instance across requests --
doing so would resurrect exactly the stale-`allowed`-after-revoke
privilege-escalation window design.md §5.6 explicitly rules out ("un
`allowed` cacheado tras un revoke es privilege-escalation, no un defecto de
performance"). `test_a_fresh_service_instance_never_sees_a_stale_memo`
guards this: a new instance always re-queries live, so a revoke is visible
on the very next request without any invalidation mechanism to get wrong.

**No structural guardrail exists today -- this contract is enforced only by
this docstring and the test above.** There is nothing stopping a future
composition-root author from wiring this as a FastAPI singleton dependency
by mistake (e.g. `Depends(get_permission_service)` backed by an
`@lru_cache`-decorated factory, or a module-level instance built once at
startup) -- that mistake would silently reintroduce the exact
privilege-escalation window this docstring warns about, and nothing in CI
or at runtime would catch it. The connection this class is constructed
with is itself request-scoped (carries per-request `SET LOCAL app.*`
GUCs), so a singleton-wiring mistake would likely surface loudly first as
connection contention -- but don't rely on that as the safety net. When
task 10.2 builds the composition root, its dependency-injection wiring for
`PermissionService` MUST be tested to confirm a fresh instance per request
(e.g. asserting the FastAPI dependency isn't `lru_cache`-wrapped), not
assumed correct because "it uses `Depends()`."

Same connection-ownership contract as the other Phase 3 postgres adapters:
takes an already-open `AsyncConnection` from `app.db.runtime_engine`
(`app_runtime`, RLS-enforced) with the request's GUCs already set.
"""

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
        """Single query resolving precedence for every catalog action at
        once (design.md §5.4) -- also warms the memo so a subsequent
        `is_allowed` for any of these actions never re-queries."""
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
