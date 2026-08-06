from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.governance.rbac.domain.permission import ActionKey


@dataclass(frozen=True)
class ActionCatalogEntry:
    key: ActionKey
    description: str
    requires_hitl: bool = False


# Keys with real authorize() call sites only — extend when adding a new call site.
ACTION_CATALOG: tuple[ActionCatalogEntry, ...] = (
    ActionCatalogEntry("appointment:create", "Schedule a new appointment"),
    ActionCatalogEntry("appointment:reschedule", "Move an appointment to a different slot"),
    ActionCatalogEntry("appointment:cancel", "Cancel an appointment"),
    ActionCatalogEntry("appointment:view", "View appointment/reminder data"),
    ActionCatalogEntry("session:revoke_all", "Admin-revoke every active session for a user"),
    ActionCatalogEntry("staff:register", "Register a new staff member"),
    ActionCatalogEntry("staff:deactivate", "Deactivate a staff member"),
    ActionCatalogEntry("shift:create", "Create a shift for a staff member"),
    ActionCatalogEntry("shift:edit", "Edit an existing shift"),
    ActionCatalogEntry("calendar:connect", "Connect a patient's Google Calendar via OAuth2"),
)


async def seed_action_catalog(conn: AsyncConnection) -> None:
    """Idempotent upsert of ACTION_CATALOG (ON CONFLICT DO NOTHING)."""
    for entry in ACTION_CATALOG:
        await conn.execute(
            text(
                """
                INSERT INTO action_permissions (key, description, requires_hitl)
                VALUES (:key, :description, :requires_hitl)
                ON CONFLICT (key) DO NOTHING
                """
            ),
            {"key": entry.key, "description": entry.description, "requires_hitl": entry.requires_hitl},
        )
