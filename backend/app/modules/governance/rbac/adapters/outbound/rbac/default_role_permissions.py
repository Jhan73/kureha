from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.governance.rbac.domain.permission import ActionKey

# NOT BUSINESS-APPROVED -- see module docstring. Loosest defensible
# assignment per role, covering every action key in `ACTION_CATALOG`
# (action_catalog.py) that a role would plausibly need in ANY clinic.
DEFAULT_DEV_ROLE_PERMISSIONS: dict[str, tuple[ActionKey, ...]] = {
    "patient": ("appointment:view", "calendar:connect"),
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
