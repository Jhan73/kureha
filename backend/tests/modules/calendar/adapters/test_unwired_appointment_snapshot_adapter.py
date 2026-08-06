import pytest

from app.modules.calendar.adapters.outbound.appointment_snapshot.unwired_adapter import (
    UnwiredAppointmentSnapshotAdapter,
)


async def test_get_snapshot_raises_not_implemented() -> None:
    adapter = UnwiredAppointmentSnapshotAdapter()

    with pytest.raises(NotImplementedError):
        await adapter.get_snapshot("t1", "appt-1")
