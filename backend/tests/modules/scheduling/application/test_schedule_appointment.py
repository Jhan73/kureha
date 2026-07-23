"""Task 7.3: `ScheduleAppointment` use case -- `authorize(ctx, action)` first
(design.md §5.3), then reserve the slot, create the appointment, and audit
in that order. Fakes only, no DB."""

from datetime import datetime, timezone

import pytest

from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType
from app.modules.governance.rbac.application.use_cases.authorize_action import (
    ActionNotPermittedError,
    AuthorizeAction,
)
from app.modules.scheduling.application.use_cases.schedule_appointment import ScheduleAppointment
from app.modules.scheduling.domain.appointment import Appointment, AppointmentStatus
from app.modules.scheduling.domain.availability import AvailabilitySlot, AvailabilityStatus
from app.modules.scheduling.domain.errors import (
    AvailabilitySlotNotFoundError,
    SlotUnavailableError,
    StaffNotAssignableError,
)
from app.shared_kernel.tenant_context import TenantContext

_T0 = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)


class _FakeAuthorizationPort:
    def __init__(self, *, allowed: bool) -> None:
        self._allowed = allowed
        self.checked: list[str] = []

    async def is_allowed(self, ctx: TenantContext, action: str) -> bool:
        self.checked.append(action)
        return self._allowed

    async def list_allowed_actions(self, ctx: TenantContext) -> set[str]:
        raise NotImplementedError


class _FakeAvailabilityRepository:
    def __init__(self, *, slot: AvailabilitySlot | None) -> None:
        self._slot = slot
        self.reserved: list[str] = []

    async def find_available_slots(self, tenant_id, *, site_id, professional_id, on_date):
        raise NotImplementedError

    async def get_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot | None:
        return self._slot

    async def reserve_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot:
        if self._slot is None or not self._slot.is_available:
            raise SlotUnavailableError(f"slot {availability_id} unavailable")
        self.reserved.append(availability_id)
        reserved_slot = AvailabilitySlot(
            id=self._slot.id,
            tenant_id=self._slot.tenant_id,
            site_id=self._slot.site_id,
            professional_id=self._slot.professional_id,
            starts_at=self._slot.starts_at,
            ends_at=self._slot.ends_at,
            status=AvailabilityStatus.RESERVED,
        )
        self._slot = reserved_slot
        return reserved_slot

    async def release_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot:
        raise NotImplementedError


class _FakeSchedulingRepository:
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create_appointment(
        self, tenant_id, *, site_id, patient_id, professional_id, availability_id, starts_at, ends_at
    ) -> Appointment:
        self.created.append(
            {
                "tenant_id": tenant_id,
                "site_id": site_id,
                "patient_id": patient_id,
                "professional_id": professional_id,
                "availability_id": availability_id,
            }
        )
        return Appointment(
            id="appt-1",
            tenant_id=tenant_id,
            site_id=site_id,
            patient_id=patient_id,
            professional_id=professional_id,
            availability_id=availability_id,
            starts_at=starts_at,
            ends_at=ends_at,
            status=AppointmentStatus.SCHEDULED,
        )

    async def get_appointment(self, tenant_id, appointment_id):
        raise NotImplementedError

    async def reschedule_appointment(self, tenant_id, appointment_id, **kwargs):
        raise NotImplementedError

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


def _available_slot() -> AvailabilitySlot:
    return AvailabilitySlot(
        id="av1", tenant_id="t1", site_id="s1", professional_id="pr1", starts_at=_T0, ends_at=_T1,
        status=AvailabilityStatus.AVAILABLE,
    )


async def test_authorize_is_checked_before_anything_else() -> None:
    authorization = _FakeAuthorizationPort(allowed=False)
    use_case = ScheduleAppointment(
        AuthorizeAction(authorization),
        _FakeAvailabilityRepository(slot=None),
        _FakeSchedulingRepository(),
        _FakeAuditLog(),
        _FakeStaffStatusPort(),
    )

    with pytest.raises(ActionNotPermittedError):
        await use_case.execute(_ctx(), patient_id="p1", professional_id="pr1", site_id="s1", availability_id="av1")

    assert authorization.checked == ["appointment:create"]


async def test_missing_slot_raises_not_found() -> None:
    authorization = _FakeAuthorizationPort(allowed=True)
    use_case = ScheduleAppointment(
        AuthorizeAction(authorization),
        _FakeAvailabilityRepository(slot=None),
        _FakeSchedulingRepository(),
        _FakeAuditLog(),
        _FakeStaffStatusPort(),
    )

    with pytest.raises(AvailabilitySlotNotFoundError):
        await use_case.execute(_ctx(), patient_id="p1", professional_id="pr1", site_id="s1", availability_id="av1")


async def test_unavailable_slot_raises_slot_unavailable() -> None:
    taken_slot = AvailabilitySlot(
        id="av1", tenant_id="t1", site_id="s1", professional_id="pr1", starts_at=_T0, ends_at=_T1,
        status=AvailabilityStatus.RESERVED,
    )
    authorization = _FakeAuthorizationPort(allowed=True)
    use_case = ScheduleAppointment(
        AuthorizeAction(authorization),
        _FakeAvailabilityRepository(slot=taken_slot),
        _FakeSchedulingRepository(),
        _FakeAuditLog(),
        _FakeStaffStatusPort(),
    )

    with pytest.raises(SlotUnavailableError):
        await use_case.execute(_ctx(), patient_id="p1", professional_id="pr1", site_id="s1", availability_id="av1")


async def test_staff_not_assignable_denies_before_any_mutation() -> None:
    """Spec `staff-registry` -> "Deactivated staff cannot be scheduled":
    checked BEFORE the slot is reserved or the appointment created (tasks.md
    task 8.4) -- neither repository must be touched on this deny."""
    authorization = _FakeAuthorizationPort(allowed=True)
    availability = _FakeAvailabilityRepository(slot=_available_slot())
    scheduling = _FakeSchedulingRepository()
    staff_status = _FakeStaffStatusPort(assignable=False)
    use_case = ScheduleAppointment(
        AuthorizeAction(authorization), availability, scheduling, _FakeAuditLog(), staff_status
    )

    with pytest.raises(StaffNotAssignableError):
        await use_case.execute(_ctx(), patient_id="p1", professional_id="pr1", site_id="s1", availability_id="av1")

    assert staff_status.checked == ["pr1"]
    assert availability.reserved == []
    assert scheduling.created == []


async def test_happy_path_reserves_creates_and_audits() -> None:
    authorization = _FakeAuthorizationPort(allowed=True)
    availability = _FakeAvailabilityRepository(slot=_available_slot())
    scheduling = _FakeSchedulingRepository()
    audit = _FakeAuditLog()
    staff_status = _FakeStaffStatusPort()
    use_case = ScheduleAppointment(AuthorizeAction(authorization), availability, scheduling, audit, staff_status)

    appointment = await use_case.execute(
        _ctx(), patient_id="p1", professional_id="pr1", site_id="s1", availability_id="av1"
    )

    assert appointment.id == "appt-1"
    assert appointment.status == AppointmentStatus.SCHEDULED
    assert staff_status.checked == ["pr1"]
    assert availability.reserved == ["av1"]
    assert scheduling.created == [
        {"tenant_id": "t1", "site_id": "s1", "patient_id": "p1", "professional_id": "pr1", "availability_id": "av1"}
    ]
    assert len(audit.recorded) == 1
    entry = audit.recorded[0]
    assert entry.tenant_id == "t1"
    assert entry.site_id == "s1"
    assert entry.actor_id == "u1"
    assert entry.actor_type == AuditActorType.USER
    assert entry.action == AuditAction.APPOINTMENT_CREATE
    assert entry.object_type == "appointment"
    assert entry.object_id == "appt-1"
