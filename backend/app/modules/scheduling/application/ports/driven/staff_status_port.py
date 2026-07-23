"""`StaffStatusPort` (design.md §6/§8.4, tasks.md task 8.4): scheduling's own
driven port for confirming a professional is currently assignable before
`ScheduleAppointment`/`RescheduleAppointment` commit a new booking onto them
(spec `staff-registry` -> "Deactivated staff cannot be scheduled").

Scheduling DEFINES this port and depends only on its abstract shape -- it
never imports `app.modules.staff` directly, mirroring
`SchedulingRepositoryPort`/`AvailabilityRepositoryPort`'s own pattern of
"the module that needs the read defines the port it needs, shaped around its
own vocabulary" (here: a bare `professional_id`, not a `StaffMember`).
Business modules never import each other's internals (backend/AGENTS.md);
the concrete implementation lives OUTSIDE this module and is wired in at the
composition root (tasks.md task 10.2, not yet built) -- see
`adapters/outbound/staff_status/unwired_adapter.py`'s module docstring for
the exact, currently-open seam.
"""

from typing import Protocol


class StaffStatusPort(Protocol):
    async def is_assignable(self, tenant_id: str, professional_id: str) -> bool:
        """Returns whether `professional_id` may currently be assigned a new
        appointment within `tenant_id`. False both when the professional's
        operational record has been deactivated (spec `staff-registry`) and
        when no matching record exists at all -- deny-by-default, the same
        posture `PermissionPolicy.resolve` (governance/rbac) takes for an
        action with no grant at all (design.md §5.2)."""
        ...
