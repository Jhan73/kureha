"""`calendar_sync` node (design.md §7.2/§8.2/§8.3, tasks.md task 11.5):
post-commit, best-effort mirror of a just-persisted appointment mutation
into the patient's Google Calendar -- only reachable (per `route_by_
calendar_sync`, this batch's `build_graph.py`) when `intent in
{"schedule","reschedule","cancel"}` AND the patient has a connected
calendar. Wires the REAL `SyncAppointmentToCalendar` use case
(`build_sync_appointment_to_calendar`, already existed since tasks.md task
10.2) -- this node's only new responsibility is resolving the arguments
that use case needs from what `persist_and_audit` (this same batch) left in
`state.outcome`.

**Never lets a sync failure fail the TURN -- `sync_appointment_to_calendar.
py`'s own module docstring's contract, respected end-to-end here too.**
Every branch below returns a `calendar_sync_status` string
(`"ok"`/`"failed"`/`"n/a"`), never raises -- the appointment mutation
already committed in `persist_and_audit`, and this node runs strictly
AFTER that commit (design.md §7.2: "el sync sigue siendo best-effort/
no-transaccional").

**Resolving the appointment's own data (`site_id`/`patient_id`/
`starts_at`/`ends_at`) -- via `AppointmentSnapshotPort`, not a fresh
cross-module import.** `persist_and_audit`'s `ActionOutcome` only carries
`result_id` (the appointment id), not the full row -- this node re-reads it
through calendar's OWN `AppointmentSnapshotPort` (`PostgresAppointmentSnapshotAdapter`,
`composition_root.py`, built for exactly this "need appointment data
without a business-module-to-business-module import" need, tasks.md task
9.5's own precedent) rather than importing `scheduling`'s repository
directly from this platform-layer node. `AppointmentSyncSnapshot` gained a
`site_id` field THIS session (`appointment_snapshot.py`'s own docstring) --
it did not carry one before, since `RetryPendingCalendarSyncs` (its only
prior caller) already had `site_id` from the `calendar_sync` row itself;
this node is the first caller with no such row to fall back on (nothing
exists yet for a FIRST sync attempt).

**FLAGGED, UNRESOLVED gap: no staff `base_role` exists for a `patient`-role
actor.** `build_sync_appointment_to_calendar`'s own docstring is explicit:
`base_role` MUST satisfy `calendar_sync_staff`
(`reception`/`professional`/`admin`) for the WRITE to the `calendar_sync`
table, and "callers with a patient actor MUST resolve a designated staff
`base_role` for this background sync flow themselves... not built here."
This node is exactly that "not built here" caller design.md never resolved
for a self-service `patient_chat`/web_form actor scheduling their OWN
appointment: `RequestContext.role == "patient"` cannot satisfy
`calendar_sync_staff` and there is no designated system/service role in
this codebase to substitute (`open_elevated_connection()` is reserved for
pre-auth flows only, per its own docstring -- reusing it here would be an
unauthorized RLS bypass, not a fix). Rather than inventing an
unauthorized role escalation, this node reports `calendar_sync_status
="failed"` for a `patient`-role actor WITHOUT attempting the sync --
matching `consent_gate`'s own precedent (batch 1) of "deny/skip
defensively + document, don't silently invent a fix outside this task's
scope". A real resolution needs either (a) a dedicated system/service role
with a `calendar_sync_staff`-equivalent grant, or (b) a design revision to
`calendar_sync`'s RLS policy to allow a patient-actor-initiated write under
narrower conditions -- neither decided here."""

from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncConnection

from app.composition_root import PostgresAppointmentSnapshotAdapter, build_sync_appointment_to_calendar
from app.modules.calendar.application.ports.driven.appointment_snapshot import AppointmentSnapshotPort
from app.modules.calendar.application.ports.driven.calendar_sync import CalendarSyncPort
from app.modules.calendar.application.ports.driven.credential_vault import CredentialVaultPort
from app.modules.calendar.domain.calendar_sync_record import CalendarSyncStatus
from app.platform.inbound.graph.state import KurehaState

_STAFF_ROLES = frozenset({"reception", "professional", "admin"})


def make_calendar_sync_node(
    conn: AsyncConnection,
    *,
    calendar_sync_port: CalendarSyncPort | None = None,
    credential_vault: CredentialVaultPort | None = None,
    appointment_snapshot: AppointmentSnapshotPort | None = None,
    sync_use_case_factory: Callable[..., Any] | None = None,
):
    """`appointment_snapshot`/`sync_use_case_factory` default to the real
    composition-root wiring -- overridable ONLY for tests (fakes, see
    `test_calendar_sync.py`)."""
    reader = appointment_snapshot if appointment_snapshot is not None else PostgresAppointmentSnapshotAdapter(conn)
    factory = sync_use_case_factory if sync_use_case_factory is not None else build_sync_appointment_to_calendar

    async def calendar_sync(state: KurehaState) -> dict:
        outcome = state.get("outcome")
        if outcome is None or not outcome.success or outcome.result_id is None:
            return {"calendar_sync_status": "n/a"}

        ctx = state["request_ctx"]
        if ctx.role not in _STAFF_ROLES:
            # FLAGGED, unresolved gap -- see this module's docstring.
            return {"calendar_sync_status": "failed"}

        snapshot = await reader.get_snapshot(ctx.tenant_id, outcome.result_id)
        if snapshot is None:
            return {"calendar_sync_status": "failed"}

        use_case = factory(
            conn, base_role=ctx.role, calendar_sync_port=calendar_sync_port, credential_vault=credential_vault
        )
        record = await use_case.execute(
            ctx.tenant_id,
            site_id=snapshot.site_id or ctx.site_id,
            appointment_id=outcome.result_id,
            patient_id=snapshot.patient_id,
            starts_at=snapshot.starts_at,
            ends_at=snapshot.ends_at,
        )

        status = "ok" if record.status is CalendarSyncStatus.OK else "failed"
        return {"calendar_sync_status": status}

    return calendar_sync
