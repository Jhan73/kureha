"""Task 7.3: `CancelAppointment` use case -- `authorize` first, cancel, then
release the freed slot and audit. Fakes only, no DB."""

from datetime import datetime, timezone

import pytest

from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType
from app.modules.governance.rbac.application.use_cases.authorize_action import (
    ActionNotPermittedError,
    AuthorizeAction,
)
from app.modules.scheduling.application.use_cases.cancel_appointment import CancelAppointment
from app.modules.scheduling.domain.appointment import Appointment, AppointmentStatus
from app.modules.scheduling.domain.errors import AppointmentNotActiveError, AppointmentNotFoundError
from app.shared_kernel.tenant_context import TenantContext

_T0 = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)


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
    def __init__(self) -> None:
        self.released: list[str] = []

    async def find_available_slots(self, tenant_id, *, site_id, professional_id, on_date):
        raise NotImplementedError

    async def get_slot(self, tenant_id, availability_id):
        raise NotImplementedError

    async def reserve_slot(self, tenant_id, availability_id):
        raise NotImplementedError

    async def release_slot(self, tenant_id: str, availability_id: str):
        self.released.append(availability_id)
        return None


class _FakeSchedulingRepository:
    def __init__(self, *, existing: Appointment | None) -> None:
        self._existing = existing
        self.cancelled: list[str] = []

    async def create_appointment(self, *args, **kwargs):
        raise NotImplementedError

    async def get_appointment(self, tenant_id: str, appointment_id: str) -> Appointment | None:
        return self._existing

    async def reschedule_appointment(self, *args, **kwargs):
        raise NotImplementedError

    async def cancel_appointment(self, tenant_id: str, appointment_id: str) -> Appointment:
        self.cancelled.append(appointment_id)
        return Appointment(
            id=appointment_id,
            tenant_id=tenant_id,
            site_id=self._existing.site_id,
            patient_id=self._existing.patient_id,
            professional_id=self._existing.professional_id,
            availability_id=self._existing.availability_id,
            starts_at=self._existing.starts_at,
            ends_at=self._existing.ends_at,
            status=AppointmentStatus.CANCELLED,
        )


class _FakeAuditLog:
    def __init__(self) -> None:
        self.recorded: list = []

    async def record(self, entry) -> str:
        self.recorded.append(entry)
        return "audit-1"


def _ctx() -> TenantContext:
    return TenantContext(tenant_id="t1", role="reception", site_id="s1", actor_id="u1")


def _existing_appointment(*, status: AppointmentStatus = AppointmentStatus.SCHEDULED) -> Appointment:
    return Appointment(
        id="appt-1", tenant_id="t1", site_id="s1", patient_id="p1", professional_id="pr1",
        availability_id="av1", starts_at=_T0, ends_at=_T1, status=status,
    )


async def test_authorize_is_checked_first() -> None:
    authorization = _FakeAuthorizationPort(allowed=False)
    use_case = CancelAppointment(
        AuthorizeAction(authorization), _FakeAvailabilityRepository(), _FakeSchedulingRepository(existing=None), _FakeAuditLog()
    )

    with pytest.raises(ActionNotPermittedError):
        await use_case.execute(_ctx(), appointment_id="appt-1")

    assert authorization.checked == ["appointment:cancel"]


async def test_missing_appointment_raises_not_found() -> None:
    use_case = CancelAppointment(
        AuthorizeAction(_FakeAuthorizationPort()), _FakeAvailabilityRepository(), _FakeSchedulingRepository(existing=None), _FakeAuditLog()
    )

    with pytest.raises(AppointmentNotFoundError):
        await use_case.execute(_ctx(), appointment_id="appt-1")


async def test_inactive_appointment_raises_not_active() -> None:
    use_case = CancelAppointment(
        AuthorizeAction(_FakeAuthorizationPort()),
        _FakeAvailabilityRepository(),
        _FakeSchedulingRepository(existing=_existing_appointment(status=AppointmentStatus.NO_SHOW)),
        _FakeAuditLog(),
    )

    with pytest.raises(AppointmentNotActiveError):
        await use_case.execute(_ctx(), appointment_id="appt-1")


async def test_happy_path_cancels_releases_slot_and_audits() -> None:
    availability = _FakeAvailabilityRepository()
    scheduling = _FakeSchedulingRepository(existing=_existing_appointment())
    audit = _FakeAuditLog()
    use_case = CancelAppointment(AuthorizeAction(_FakeAuthorizationPort()), availability, scheduling, audit)

    cancelled = await use_case.execute(_ctx(), appointment_id="appt-1")

    assert cancelled.status == AppointmentStatus.CANCELLED
    assert scheduling.cancelled == ["appt-1"]
    assert availability.released == ["av1"]
    assert len(audit.recorded) == 1
    entry = audit.recorded[0]
    assert entry.action == AuditAction.APPOINTMENT_CANCEL
    assert entry.actor_type == AuditActorType.USER
    assert entry.object_id == "appt-1"
