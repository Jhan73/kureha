"""Code-driven seed for the global `action_permissions` catalog (design.md
§4.4/§16, tasks.md task 3.6).

Before this task, nothing populated `action_permissions` anywhere in the
codebase -- `AuthorizeAction`/`PermissionService` therefore denied every
action by construction against a real Postgres, a gap PR8's review found
masked by every use-case-level test's `_FakeAuthorizationPort` (which never
touches the table at all). This module closes the MECHANISM gap only: the
catalog's shape (which keys exist, their `description`/`requires_hitl`), not
the per-tenant role->action grants (see `default_role_permissions.py` for
that placeholder, and design.md §16 for why the grant CONTENT is out of
scope here: "input de negocio pendiente").

`action_permissions` is a global, tenant-agnostic catalog with no RLS
(migration 613f9ea3526f's own docstring: "`action_permissions` is explicitly
documented as a global catalog with 'sin RLS' (§4.4)") -- seeding it needs no
`app.*` GUC context at all, unlike every tenant-scoped seed helper in
`tests/rls/helpers.py`.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.governance.rbac.domain.permission import ActionKey


@dataclass(frozen=True)
class ActionCatalogEntry:
    key: ActionKey
    description: str
    requires_hitl: bool = False


# Exhaustive as of this seed's authoring: every `resource:action` key actually
# referenced by an `authorize.execute(ctx, action=...)` call site in
# `app/modules/**/application/use_cases/*.py` today (grepped, not guessed).
# design.md §5.1's catalog comment additionally lists `appointment:cancel_bulk`
# as a FUTURE key -- it has no call site yet (`RiskPolicy`/bulk-cancel
# orchestration is Phase 11 work, not built), so seeding it here would be
# inventing data ahead of the code that needs it. `calendar:connect` WAS in
# that same "future" bucket until this session (tasks.md Phase 9,
# `ConnectPatientCalendar` -- app/modules/calendar/application/use_cases/
# connect_patient_calendar.py) added the real call site; added here in the
# SAME PR per this task's own instructions (a new `authorize()` call site
# must register its key here or the action becomes permanently
# undeniable/ungrantable -- the exact gap task 3.6 exists to close, flagged
# again so it doesn't silently regress). Extend this tuple whenever a new
# `authorize()` call site is introduced elsewhere in the codebase.
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
    """Upserts `ACTION_CATALOG` into `action_permissions`.

    `ON CONFLICT (key) DO NOTHING` makes this idempotent -- safe to call once
    per test session (see `tests/conftest.py`'s `_migrated_schema` pattern) or
    from a future startup hook, without duplicating rows or clobbering a
    `requires_hitl`/`bulk_cancel_threshold` value a real deployment may have
    already tuned via design.md §16's runtime-UPDATE escape hatch.
    """
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
