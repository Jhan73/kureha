"""Task 7.1: `Appointment` domain (design.md §4.1's `appointments` table
shape). Pure value object -- state-transition invariants only, no IO."""

from datetime import datetime, timezone

import pytest

from app.modules.scheduling.domain.appointment import Appointment, AppointmentStatus
from app.modules.scheduling.domain.errors import AppointmentNotActiveError

_T0 = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)


def _appointment(*, status: AppointmentStatus = AppointmentStatus.SCHEDULED) -> Appointment:
    return Appointment(
        id="a1",
        tenant_id="t1",
        site_id="s1",
        patient_id="p1",
        professional_id="pr1",
        availability_id="av1",
        starts_at=_T0,
        ends_at=_T1,
        status=status,
    )


@pytest.mark.parametrize("status", [AppointmentStatus.SCHEDULED, AppointmentStatus.RESCHEDULED])
def test_is_active_for_scheduled_or_rescheduled(status: AppointmentStatus) -> None:
    assert _appointment(status=status).is_active is True


@pytest.mark.parametrize(
    "status",
    [AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW],
)
def test_is_not_active_for_terminal_statuses(status: AppointmentStatus) -> None:
    assert _appointment(status=status).is_active is False


def test_ensure_active_raises_when_not_active() -> None:
    appointment = _appointment(status=AppointmentStatus.CANCELLED)

    with pytest.raises(AppointmentNotActiveError):
        appointment.ensure_active()


def test_ensure_active_does_not_raise_when_active() -> None:
    _appointment(status=AppointmentStatus.SCHEDULED).ensure_active()
