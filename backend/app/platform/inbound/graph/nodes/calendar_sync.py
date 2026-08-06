from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncConnection

from app.composition_root import PostgresAppointmentSnapshotAdapter, build_sync_appointment_to_calendar
from app.modules.calendar.application.ports.driven.appointment_snapshot import AppointmentSnapshotPort
from app.modules.calendar.application.ports.driven.calendar_sync import CalendarSyncPort
from app.modules.calendar.application.ports.driven.credential_vault import CredentialVaultPort
from app.modules.calendar.domain.calendar_sync_record import CalendarSyncStatus
from app.platform.inbound.graph.state import KurehaState
from app.platform.inbound.graph.streaming.status_writer import emit_status

_STAFF_ROLES = frozenset({"reception", "professional", "admin"})


def make_calendar_sync_node(
    conn: AsyncConnection,
    *,
    calendar_sync_port: CalendarSyncPort | None = None,
    credential_vault: CredentialVaultPort | None = None,
    appointment_snapshot: AppointmentSnapshotPort | None = None,
    sync_use_case_factory: Callable[..., Any] | None = None,
):
    """`appointment_snapshot` / `sync_use_case_factory` overrides are for tests only."""
    reader = appointment_snapshot if appointment_snapshot is not None else PostgresAppointmentSnapshotAdapter(conn)
    factory = sync_use_case_factory if sync_use_case_factory is not None else build_sync_appointment_to_calendar

    async def calendar_sync(state: KurehaState) -> dict:
        outcome = state.get("outcome")
        if outcome is None or not outcome.success or outcome.result_id is None:
            return {"calendar_sync_status": "n/a"}

        ctx = state["request_ctx"]
        if ctx.role not in _STAFF_ROLES:
            # Patient-role calendar sync not supported on this path.
            return {"calendar_sync_status": "failed"}

        snapshot = await reader.get_snapshot(ctx.tenant_id, outcome.result_id)
        if snapshot is None:
            return {"calendar_sync_status": "failed"}

        # Post-commit admin step, not an RBAC-gated action.
        emit_status(phase="syncing_calendar", label="Sincronizando con Google Calendar")
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
