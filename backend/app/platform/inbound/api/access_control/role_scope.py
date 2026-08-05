"""`set_role_scope`/`scoped_as_patient` (design.md §4.2, tasks.md task 10.2):
a mid-transaction `SET LOCAL app.role`/`app.patient_id`/`app.professional_id`
re-scope, for the ONE documented case in this codebase where a single
logical flow needs to satisfy two different, mutually-exclusive RLS role
predicates on the SAME connection/transaction.

**The exact case this exists for:** `SyncAppointmentToCalendar`
(application/use_cases/sync_appointment_to_calendar.py, tasks.md task 9.4)
reads `calendar_credentials` (policy `calendar_credentials_self` --
`app.role='patient'` AND `app.patient_id` matching the row) and writes
`calendar_sync` (policy `calendar_sync_staff` -- `app.role IN
('reception','professional','admin')`) in the same flow. No single
`app.role` value satisfies both. See `CalendarCredentialRepositoryPort`'s
and `CalendarSyncRepositoryPort`'s module docstrings for the full RLS
detail, and `sync_appointment_to_calendar.py`'s own module docstring for
why this composition-root-level fix (not a use-case-level one) is the
correct place to resolve it: the use case's own code has no reason to know
about RLS role-switching, that is exactly this platform-layer concern.

**Safe within one transaction** -- `tests/rls/helpers.py`'s own docstring:
"Re-calling set_app_context with a different role later in the SAME
transaction is safe and expected -- RLS visibility is re-evaluated per
query from the GUCs live at query time, not fixed at INSERT time."

**Why literal string interpolation, not bind parameters:** same constraint
`session_context.py`'s module docstring documents -- `SET`/`SET LOCAL` do
not accept bind parameters over the extended query protocol. Safe here for
the identical reason: `role` is always a fixed role-name constant from
application code (never raw request input), and `patient_id`/
`professional_id` are always UUIDs already resolved from a DB row (an
appointment's `patient_id`, or the acting staff actor's own id) -- never
embed a caller-supplied string here."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_NIL_UUID = "00000000-0000-0000-0000-000000000000"


async def set_role_scope(
    conn: AsyncConnection,
    *,
    role: str,
    patient_id: str | None = None,
    professional_id: str | None = None,
) -> None:
    """Sets `app.role`/`app.patient_id`/`app.professional_id` for the
    lifetime of the current transaction on `conn`, leaving `app.tenant_id`/
    `app.site_id`/`app.user_id` untouched (those never need to change
    mid-flow for the documented use case above). Absent `patient_id`/
    `professional_id` fall back to the nil-UUID sentinel, same convention
    as `session_context.py`/`tests/rls/helpers.py`, so `current_setting`
    never raises `unrecognized configuration parameter` for a GUC that
    genuinely has no value in this scope."""
    await conn.execute(text(f"SET LOCAL app.role = '{role}'"))
    await conn.execute(text(f"SET LOCAL app.patient_id = '{patient_id or _NIL_UUID}'"))
    await conn.execute(text(f"SET LOCAL app.professional_id = '{professional_id or _NIL_UUID}'"))


@asynccontextmanager
async def scoped_as_patient(conn: AsyncConnection, *, patient_id: str, restore_role: str) -> AsyncIterator[None]:
    """Temporarily re-scopes `conn` to `app.role='patient'` + `patient_id`
    for the duration of the `async with` block, restoring `restore_role`
    (and clearing `patient_id`/`professional_id` back to the nil sentinel)
    on exit -- even if the block raises, so a failed credential read/decrypt
    never leaves the connection stuck in patient-scope for whatever staff-
    scoped write runs next in the same transaction."""
    await set_role_scope(conn, role="patient", patient_id=patient_id)
    try:
        yield
    finally:
        await set_role_scope(conn, role=restore_role)


@asynccontextmanager
async def scoped_as_admin(conn: AsyncConnection, *, restore_role: str) -> AsyncIterator[None]:
    """Second documented case for this module's re-scoping mechanism (added
    staff-invite batch): `users`' RLS write policy (`users_admin_write`,
    migration 613f9ea3526f) permits INSERT/UPDATE/DELETE ONLY when
    `current_setting('app.role') = 'admin'` literally -- `reception`, which
    `staff:register` (RBAC) also grants (`default_role_permissions.py`), is
    NOT in that predicate (unlike `users_staff_select`'s SELECT-only policy,
    which does include `reception`). Confirmed empirically: a real
    `reception` actor's own runtime connection raised
    `InsufficientPrivilegeError` inserting into `users` without this
    elevation. Since RBAC (`AuthorizeAction`, `staff:register`) already
    authorizes the calling actor for this exact action BEFORE
    `composition_root.build_provision_staff_identity`'s wrapper ever reaches
    this scope (`staff.py` router's own `_require_authorized`), this
    temporary elevation does not widen who can reach this code path -- it
    only satisfies a stricter RLS predicate than RBAC's own gate for a role
    RBAC already approved, the same "two independent, both-must-pass
    planes" relationship design.md §5.1 describes generally."""
    await set_role_scope(conn, role="admin")
    try:
        yield
    finally:
        await set_role_scope(conn, role=restore_role)
