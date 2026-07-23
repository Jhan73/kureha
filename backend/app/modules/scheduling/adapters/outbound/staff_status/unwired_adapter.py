"""`UnwiredStaffStatusAdapter`: the ONE deliberately-open seam task 8.4 leaves
for the Phase 10 composition root (tasks.md task 10.2, not yet built).

`ScheduleAppointment`/`RescheduleAppointment` are fully wired against
`StaffStatusPort` (application/ports/driven/staff_status_port.py) and tested
with a fake double at the use-case level (tests/modules/scheduling/
application/test_{schedule,reschedule}_appointment.py) -- but a real
implementation needs `staff_members` data, which lives in `modules.staff`.
Business modules never import each other's internals directly
(backend/AGENTS.md), so the concrete adapter cannot be built here without
either:

1. A future cross-cutting read (e.g. a `staff`-owned adapter implementing
   THIS port, constructed from `staff`'s own `StaffRepositoryPort`, and
   handed to scheduling's use cases only by the composition root -- the same
   indirection `modules.tenancy`'s `GetTenant` is meant to be consumed
   through by other modules once Phase 10 wires it), or
2. A scheduling-owned Postgres adapter querying `staff_members` directly by
   SQL (no Python import, but couples scheduling to staff's private schema
   -- rejected here as inconsistent with every other cross-module boundary
   in this codebase, none of which reach into another module's tables).

Neither can be decided or built without the composition root itself (out of
scope for tasks.md task 8.4 -- "do not fabricate the composition root
itself"). This class exists ONLY so scheduling's own wiring has a concrete,
importable class to reference until then. It MUST NEVER be used on a real
request path: it raises `NotImplementedError` unconditionally.

**TODO(Phase 10, tasks.md task 10.2):** replace every reference to this
class in the composition root with a real `StaffStatusPort` adapter (option
1 above is the recommended default, to keep staff's schema encapsulated)."""

class UnwiredStaffStatusAdapter:
    """Duck-types `StaffStatusPort` (application/ports/driven/
    staff_status_port.py) -- matches this codebase's own convention of
    adapters never inheriting their Protocol (see e.g.
    `PostgresSchedulingRepository`/`PostgresTenantRepository`, neither of
    which subclasses its port)."""

    async def is_assignable(self, tenant_id: str, professional_id: str) -> bool:
        raise NotImplementedError(
            "UnwiredStaffStatusAdapter is a placeholder -- wire a real StaffStatusPort "
            "implementation at the composition root (tasks.md task 10.2) before any "
            "real request reaches ScheduleAppointment/RescheduleAppointment."
        )
