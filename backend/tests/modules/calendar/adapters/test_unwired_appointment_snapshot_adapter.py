"""Task 9.5: `UnwiredAppointmentSnapshotAdapter` -- the intentionally-not-
implemented `AppointmentSnapshotPort` stub marking the open seam this task
leaves for the Phase 10 composition root. Structural: one behavior, one
possible output (always raises) -- triangulation skipped, same rationale
as `modules.scheduling`'s `test_unwired_staff_status_adapter.py`."""

import pytest

from app.modules.calendar.adapters.outbound.appointment_snapshot.unwired_adapter import (
    UnwiredAppointmentSnapshotAdapter,
)


async def test_get_snapshot_raises_not_implemented() -> None:
    adapter = UnwiredAppointmentSnapshotAdapter()

    with pytest.raises(NotImplementedError):
        await adapter.get_snapshot("t1", "appt-1")
