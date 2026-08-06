import pytest

from datetime import datetime, timezone

from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType
from app.modules.governance.rbac.application.use_cases.authorize_action import (
    ActionNotPermittedError,
    AuthorizeAction,
)
from app.modules.scheduling.application.use_cases.send_reminder import SendReminder
from app.modules.scheduling.domain.appointment import Appointment, AppointmentStatus
from app.modules.scheduling.domain.errors import AppointmentNotFoundError
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


class _FakeSchedulingRepository:
    def __init__(self, *, existing: Appointment | None) -> None:
        self._existing = existing

    async def create_appointment(self, *args, **kwargs):
        raise NotImplementedError

    async def get_appointment(self, tenant_id: str, appointment_id: str) -> Appointment | None:
        return self._existing

    async def reschedule_appointment(self, *args, **kwargs):
        raise NotImplementedError

    async def cancel_appointment(self, tenant_id, appointment_id):
        raise NotImplementedError


class _FakeReminderChannel:
    def __init__(self, *, delivered: bool = True, raises: bool = False) -> None:
        self._delivered = delivered
        self._raises = raises
        self.sent_for: list[str] = []

    async def send(self, appointment: Appointment, *, patient_id: str) -> bool:
        self.sent_for.append(appointment.id)
        if self._raises:
            raise RuntimeError("channel unreachable")
        return self._delivered


class _FakeAuditLog:
    def __init__(self) -> None:
        self.recorded: list = []

    async def record(self, entry) -> str:
        self.recorded.append(entry)
        return "audit-1"


def _ctx() -> TenantContext:
    return TenantContext(tenant_id="t1", role="reception", site_id="s1", actor_id="u1")


def _existing_appointment() -> Appointment:
    return Appointment(
        id="appt-1", tenant_id="t1", site_id="s1", patient_id="p1", professional_id="pr1",
        availability_id="av1", starts_at=_T0, ends_at=_T1, status=AppointmentStatus.SCHEDULED,
    )


async def test_authorize_is_checked_first() -> None:
    authorization = _FakeAuthorizationPort(allowed=False)
    use_case = SendReminder(
        AuthorizeAction(authorization), _FakeSchedulingRepository(existing=None), _FakeReminderChannel(), _FakeAuditLog()
    )

    with pytest.raises(ActionNotPermittedError):
        await use_case.execute(_ctx(), appointment_id="appt-1")

    assert authorization.checked == ["appointment:view"]


async def test_missing_appointment_raises_not_found() -> None:
    use_case = SendReminder(
        AuthorizeAction(_FakeAuthorizationPort()), _FakeSchedulingRepository(existing=None), _FakeReminderChannel(), _FakeAuditLog()
    )

    with pytest.raises(AppointmentNotFoundError):
        await use_case.execute(_ctx(), appointment_id="appt-1")


async def test_successful_delivery_returns_true_and_audits() -> None:
    channel = _FakeReminderChannel(delivered=True)
    audit = _FakeAuditLog()
    use_case = SendReminder(
        AuthorizeAction(_FakeAuthorizationPort()), _FakeSchedulingRepository(existing=_existing_appointment()), channel, audit
    )

    delivered = await use_case.execute(_ctx(), appointment_id="appt-1")

    assert delivered is True
    assert channel.sent_for == ["appt-1"]
    assert len(audit.recorded) == 1
    entry = audit.recorded[0]
    assert entry.action == AuditAction.APPOINTMENT_REMINDER_SENT
    assert entry.actor_type == AuditActorType.USER
    assert entry.object_id == "appt-1"
    assert entry.payload == {"delivered": True}


async def test_failed_delivery_returns_false_and_audits_without_raising() -> None:
    channel = _FakeReminderChannel(delivered=False)
    audit = _FakeAuditLog()
    use_case = SendReminder(
        AuthorizeAction(_FakeAuthorizationPort()), _FakeSchedulingRepository(existing=_existing_appointment()), channel, audit
    )

    delivered = await use_case.execute(_ctx(), appointment_id="appt-1")

    assert delivered is False
    assert audit.recorded[0].payload == {"delivered": False}


async def test_channel_exception_does_not_break_scheduling_flow() -> None:
    channel = _FakeReminderChannel(raises=True)
    audit = _FakeAuditLog()
    use_case = SendReminder(
        AuthorizeAction(_FakeAuthorizationPort()), _FakeSchedulingRepository(existing=_existing_appointment()), channel, audit
    )

    delivered = await use_case.execute(_ctx(), appointment_id="appt-1")

    assert delivered is False
    assert audit.recorded[0].payload == {"delivered": False, "error": "channel unreachable"}
