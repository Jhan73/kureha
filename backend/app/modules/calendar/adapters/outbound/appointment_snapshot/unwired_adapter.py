"""`UnwiredAppointmentSnapshotAdapter`: the deliberately-open seam task 9.5
leaves for the Phase 10 composition root (tasks.md task 10.2, not yet
built) -- exact same shape and rationale as `modules.scheduling`'s
`UnwiredStaffStatusAdapter` (adapters/outbound/staff_status/unwired_adapter.py,
tasks.md task 8.4).

`RetryPendingCalendarSyncs` is fully wired against `AppointmentSnapshotPort`
(application/ports/driven/appointment_snapshot.py) and tested with a fake
double at the use-case level -- but a real implementation needs
`appointments` data, which lives in `modules.scheduling`. Business modules
never import each other's internals directly (backend/AGENTS.md), so the
concrete adapter cannot be built here without the composition root
resolving the same two options `UnwiredStaffStatusAdapter`'s docstring
lays out (a `scheduling`-owned adapter implementing THIS port, vs. a
`calendar`-owned adapter querying `appointments` by raw SQL -- rejected for
the same reason: no other cross-module boundary in this codebase reaches
into another module's tables).

This class exists ONLY so calendar's own wiring has a concrete, importable
class to reference until then. It MUST NEVER be used on a real request/job
path: it raises `NotImplementedError` unconditionally.

**TODO(Phase 10, tasks.md task 10.2):** replace every reference to this
class in the composition root with a real `AppointmentSnapshotPort`
adapter."""


class UnwiredAppointmentSnapshotAdapter:
    """Duck-types `AppointmentSnapshotPort` (application/ports/driven/
    appointment_snapshot.py) -- matches this codebase's convention of
    adapters never inheriting their Protocol."""

    async def get_snapshot(self, tenant_id: str, appointment_id: str):
        raise NotImplementedError(
            "UnwiredAppointmentSnapshotAdapter is a placeholder -- wire a real "
            "AppointmentSnapshotPort implementation at the composition root "
            "(tasks.md task 10.2) before RetryPendingCalendarSyncs runs against a "
            "real request/job path."
        )
