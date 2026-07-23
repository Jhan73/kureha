"""Task 7.3: `RescheduleAppointment` use case -- `authorize` first, then
release the old slot, reserve the new one, and audit. Fakes only, no DB."""

from datetime import datetime, timezone

import pytest

from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType
from app.modules.governance.rbac.application.use_cases.authorize_action import (
    ActionNotPermittedError,
    AuthorizeAction,
)
from app.modules.scheduling.application.use_cases.reschedule_appointment import RescheduleAppointment
from app.modules.scheduling.domain.appointment import Appointment, AppointmentStatus
from app.modules.scheduling.domain.availability import AvailabilitySlot, AvailabilityStatus
from app.modules.scheduling.domain.errors import (
    AppointmentNotActiveError,
    AppointmentNotFoundError,
    AvailabilitySlotNotFoundError,
    SlotUnavailableError,
    StaffNotAssignableError,
)
from app.shared_kernel.tenant_context import TenantContext

_T0 = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
_T2 = datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc)
_T3 = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)


class _FakeAuthorizationPort:
    def __init__(self, *, allowed: bool = True) -> None:
        self._allowed = allowed
        self.checked: list[str] = []

    async def is_allowed(self, ctx, action) -> bool:
        self.checked.append(action)
        return self._allowed

    async def list_allowed_actions(self, ctx):
        raise NotImplementedError


class _FakeAvailabilityRepository:
    def __init__(self, *, slots: dict[str, AvailabilitySlot]) -> None:
        self._slots = slots
        self.reserved: list[str] = []
        self.released: list[str] = []

    async def find_available_slots(self, tenant_id, *, site_id, professional_id, on_date):
        raise NotImplementedError

    async def get_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot | None:
        return self._slots.get(availability_id)

    async def reserve_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot:
        slot = self._slots.get(availability_id)
        if slot is None or not slot.is_available:
            raise SlotUnavailableError(f"slot {availability_id} unavailable")
        self.reserved.append(availability_id)
        return slot

    async def release_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot:
        self.released.append(availability_id)
        return self._slots.get(availability_id)


class _FakeSchedulingRepository:
    def __init__(self, *, existing: Appointment | None) -> None:
        self._existing = existing
        self.rescheduled: list[dict] = []

    async def create_appointment(self, *args, **kwargs):
        raise NotImplementedError

    async def get_appointment(self, tenant_id: str, appointment_id: str) -> Appointment | None:
        return self._existing

    async def reschedule_appointment(
        self, tenant_id, appointment_id, *, professional_id, availability_id, starts_at, ends_at
    ) -> Appointment:
        self.rescheduled.append(
            {"appointment_id": appointment_id, "professional_id": professional_id, "availability_id": availability_id}
        )
        return Appointment(
            id=appointment_id,
            tenant_id=tenant_id,
            site_id=self._existing.site_id,
            patient_id=self._existing.patient_id,
            professional_id=professional_id,
            availability_id=availability_id,
            starts_at=starts_at,
            ends_at=ends_at,
            status=AppointmentStatus.RESCHEDULED,
        )

    async def cancel_appointment(self, tenant_id, appointment_id):
        raise NotImplementedError


class _FakeAuditLog:
    def __init__(self) -> None:
        self.recorded: list = []

    async def record(self, entry) -> str:
        self.recorded.append(entry)
        return "audit-1"


class _FakeStaffStatusPort:
    def __init__(self, *, assignable: bool = True) -> None:
        self._assignable = assignable
        self.checked: list[str] = []

    async def is_assignable(self, tenant_id: str, professional_id: str) -> bool:
        self.checked.append(professional_id)
        return self._assignable


def _ctx() -> TenantContext:
    return TenantContext(tenant_id="t1", role="reception", site_id="s1", actor_id="u1")


def _existing_appointment(*, status: AppointmentStatus = AppointmentStatus.SCHEDULED) -> Appointment:
    return Appointment(
        id="appt-1", tenant_id="t1", site_id="s1", patient_id="p1", professional_id="pr1",
        availability_id="av-old", starts_at=_T0, ends_at=_T1, status=status,
    )


def _new_slot(*, status: AvailabilityStatus = AvailabilityStatus.AVAILABLE) -> AvailabilitySlot:
    return AvailabilitySlot(
        id="av-new", tenant_id="t1", site_id="s1", professional_id="pr2", starts_at=_T2, ends_at=_T3, status=status,
    )


async def test_authorize_is_checked_first() -> None:
    authorization = _FakeAuthorizationPort(allowed=False)
    use_case = RescheduleAppointment(
        AuthorizeAction(authorization),
        _FakeAvailabilityRepository(slots={}),
        _FakeSchedulingRepository(existing=None),
        _FakeAuditLog(),
        _FakeStaffStatusPort(),
    )

    with pytest.raises(ActionNotPermittedError):
        await use_case.execute(_ctx(), appointment_id="appt-1", new_availability_id="av-new")

    assert authorization.checked == ["appointment:reschedule"]


async def test_missing_appointment_raises_not_found() -> None:
    use_case = RescheduleAppointment(
        AuthorizeAction(_FakeAuthorizationPort()),
        _FakeAvailabilityRepository(slots={}),
        _FakeSchedulingRepository(existing=None),
        _FakeAuditLog(),
        _FakeStaffStatusPort(),
    )

    with pytest.raises(AppointmentNotFoundError):
        await use_case.execute(_ctx(), appointment_id="appt-1", new_availability_id="av-new")


async def test_inactive_appointment_raises_not_active() -> None:
    use_case = RescheduleAppointment(
        AuthorizeAction(_FakeAuthorizationPort()),
        _FakeAvailabilityRepository(slots={}),
        _FakeSchedulingRepository(existing=_existing_appointment(status=AppointmentStatus.CANCELLED)),
        _FakeAuditLog(),
        _FakeStaffStatusPort(),
    )

    with pytest.raises(AppointmentNotActiveError):
        await use_case.execute(_ctx(), appointment_id="appt-1", new_availability_id="av-new")


async def test_missing_new_slot_raises_not_found() -> None:
    use_case = RescheduleAppointment(
        AuthorizeAction(_FakeAuthorizationPort()),
        _FakeAvailabilityRepository(slots={}),
        _FakeSchedulingRepository(existing=_existing_appointment()),
        _FakeAuditLog(),
        _FakeStaffStatusPort(),
    )

    with pytest.raises(AvailabilitySlotNotFoundError):
        await use_case.execute(_ctx(), appointment_id="appt-1", new_availability_id="av-new")


async def test_unavailable_new_slot_raises_slot_unavailable() -> None:
    use_case = RescheduleAppointment(
        AuthorizeAction(_FakeAuthorizationPort()),
        _FakeAvailabilityRepository(slots={"av-new": _new_slot(status=AvailabilityStatus.RESERVED)}),
        _FakeSchedulingRepository(existing=_existing_appointment()),
        _FakeAuditLog(),
        _FakeStaffStatusPort(),
    )

    with pytest.raises(SlotUnavailableError):
        await use_case.execute(_ctx(), appointment_id="appt-1", new_availability_id="av-new")


async def test_staff_not_assignable_denies_before_any_mutation() -> None:
    """Spec `staff-registry` -> "Deactivated staff cannot be scheduled":
    checked against the NEW slot's professional (the target of the move),
    BEFORE the old slot is released or the new one reserved (tasks.md task
    8.4) -- neither repository must be touched on this deny."""
    availability = _FakeAvailabilityRepository(slots={"av-new": _new_slot()})
    scheduling = _FakeSchedulingRepository(existing=_existing_appointment())
    staff_status = _FakeStaffStatusPort(assignable=False)
    use_case = RescheduleAppointment(
        AuthorizeAction(_FakeAuthorizationPort()), availability, scheduling, _FakeAuditLog(), staff_status
    )

    with pytest.raises(StaffNotAssignableError):
        await use_case.execute(_ctx(), appointment_id="appt-1", new_availability_id="av-new")

    assert staff_status.checked == ["pr2"]
    assert availability.reserved == []
    assert availability.released == []
    assert scheduling.rescheduled == []


async def test_happy_path_releases_old_reserves_new_and_audits() -> None:
    availability = _FakeAvailabilityRepository(slots={"av-new": _new_slot()})
    scheduling = _FakeSchedulingRepository(existing=_existing_appointment())
    audit = _FakeAuditLog()
    staff_status = _FakeStaffStatusPort()
    use_case = RescheduleAppointment(
        AuthorizeAction(_FakeAuthorizationPort()), availability, scheduling, audit, staff_status
    )

    updated = await use_case.execute(_ctx(), appointment_id="appt-1", new_availability_id="av-new")

    assert updated.status == AppointmentStatus.RESCHEDULED
    assert updated.professional_id == "pr2"
    assert staff_status.checked == ["pr2"]
    assert availability.released == ["av-old"]
    assert availability.reserved == ["av-new"]
    assert scheduling.rescheduled == [
        {"appointment_id": "appt-1", "professional_id": "pr2", "availability_id": "av-new"}
    ]
    assert len(audit.recorded) == 1
    entry = audit.recorded[0]
    assert entry.action == AuditAction.APPOINTMENT_RESCHEDULE
    assert entry.actor_type == AuditActorType.USER
    assert entry.object_id == "appt-1"
