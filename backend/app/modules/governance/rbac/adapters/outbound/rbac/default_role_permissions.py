"""Placeholder, dev/test-only `role_permissions` seeding mechanism for one
tenant (design.md §4.4/§16, tasks.md task 3.6).

**NOT BUSINESS-APPROVED.** Design.md §16 flags the real per-tenant
role->action matrix as "input de negocio pendiente" -- explicit business
input this session may not invent. `DEFAULT_DEV_ROLE_PERMISSIONS` below
exists ONLY to unblock local/dev/integration testing of `AuthorizeAction`
end-to-end against a real Postgres (the gap PR8's review found: with no seed
data at all, every action was denied by construction, masked in unit tests
by `_FakeAuthorizationPort`). It grants a loosely-plausible set of actions
per role -- a MECHANISM demonstration, not a sign-off'd permission policy.

**MUST be replaced with the business-approved matrix before any non-dev
environment is provisioned.** Do not ship this matrix to staging/production
as-is; whoever builds it should load the real matrix through this same
`seed_default_role_permissions` shape (or its production successor), not
invent a second seeding path.

`role_permissions` is tenant-scoped (`PRIMARY KEY (tenant_id, role, action)`,
design.md §4.4) -- unlike `action_permissions`'s global catalog, there is no
fixed row a raw migration INSERT could target for arbitrary tenants created
later. The seeding mechanism is therefore a plain function taking a
`tenant_id`, callable today from test fixtures/conftest, and (documented,
not built) from wherever tenants get created in Phase 10's composition root
/ tenant-provisioning flow -- see tasks.md task 10.2. **TODO(Phase 10):**
call `seed_default_role_permissions` (or its production replacement) at
tenant-creation time once that flow exists; nothing calls it automatically
today.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.governance.rbac.domain.permission import ActionKey

# NOT BUSINESS-APPROVED -- see module docstring. Loosest defensible
# assignment per role, covering every action key in `ACTION_CATALOG`
# (action_catalog.py) that a role would plausibly need in ANY clinic.
DEFAULT_DEV_ROLE_PERMISSIONS: dict[str, tuple[ActionKey, ...]] = {
    "patient": ("appointment:view",),
    "professional": (
        "appointment:view",
        "appointment:reschedule",
    ),
    "reception": (
        "appointment:create",
        "appointment:reschedule",
        "appointment:cancel",
        "appointment:view",
        "staff:register",
        "staff:deactivate",
        "shift:create",
        "shift:edit",
    ),
    "admin": (
        "appointment:create",
        "appointment:reschedule",
        "appointment:cancel",
        "appointment:view",
        "session:revoke_all",
        "staff:register",
        "staff:deactivate",
        "shift:create",
        "shift:edit",
    ),
}


async def seed_default_role_permissions(conn: AsyncConnection, tenant_id: str) -> None:
    """Grants `DEFAULT_DEV_ROLE_PERMISSIONS` for one tenant.

    Requires `action_permissions` to already carry every action key used
    below (FK `role_permissions.action -> action_permissions.key`) -- call
    `seed_action_catalog` (action_catalog.py) first. Idempotent via
    `ON CONFLICT (tenant_id, role, action) DO NOTHING`.
    """
    for role, actions in DEFAULT_DEV_ROLE_PERMISSIONS.items():
        for action in actions:
            await conn.execute(
                text(
                    """
                    INSERT INTO role_permissions (tenant_id, role, action, allowed)
                    VALUES (:tenant_id, :role, :action, true)
                    ON CONFLICT (tenant_id, role, action) DO NOTHING
                    """
                ),
                {"tenant_id": tenant_id, "role": role, "action": action},
            )
