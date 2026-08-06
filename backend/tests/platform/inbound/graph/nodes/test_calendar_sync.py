from datetime import datetime, timezone

import pytest

from app.modules.calendar.application.ports.driven.appointment_snapshot import AppointmentSyncSnapshot
from app.modules.calendar.domain.calendar_sync_record import CalendarSyncRecord, CalendarSyncStatus
from app.platform.inbound.graph.nodes.calendar_sync import make_calendar_sync_node
from app.platform.inbound.graph.state import ActionOutcome, KurehaState, RequestContext


class _FakeAppointmentSnapshotReader:
    def __init__(self, *, snapshot: AppointmentSyncSnapshot | None) -> None:
        self._snapshot = snapshot
        self.calls: list[tuple[str, str]] = []

    async def get_snapshot(self, tenant_id: str, appointment_id: str):
        self.calls.append((tenant_id, appointment_id))
        return self._snapshot


class _FakeSyncUseCase:
    def __init__(self, *, record: CalendarSyncRecord) -> None:
        self._record = record
        self.calls: list[dict] = []

    async def execute(self, tenant_id, **kwargs):
        self.calls.append({"tenant_id": tenant_id, **kwargs})
        return self._record


def _record(status: CalendarSyncStatus) -> CalendarSyncRecord:
    return CalendarSyncRecord(
        id="sync-1",
        tenant_id="t1",
        site_id="s1",
        appointment_id="appt-1",
        idempotency_key="k",
        status=status,
        attempts=1,
        updated_at=datetime.now(timezone.utc),
    )


def _state(*, intent: str, role: str, outcome: ActionOutcome | None) -> KurehaState:
    return {
        "request_ctx": RequestContext(tenant_id="t1", role=role, site_id="s1", user_id="u1", patient_id="p1"),
        "channel": "staff_copilot",
        "channel_message": "x",
        "intent": intent,
        "scope_ok": True,
        "consent_ok": True,
        "allowed_actions": None,
        "proposed_action": None,
        "rbac_ok": True,
        "risk_level": "low",
        "confirmation": "affirmed",
        "approval": None,
        "outcome": outcome,
        "audit_ref": None,
        "response_text": None,
        "response_scope_ok": None,
        "calendar_sync_status": None,
        "suggestions": None,
    }


@pytest.mark.asyncio
async def test_syncs_successfully_for_a_staff_actor_after_schedule() -> None:
    snapshot = AppointmentSyncSnapshot(
        patient_id="p1", starts_at=datetime.now(timezone.utc), ends_at=datetime.now(timezone.utc), site_id="s1"
    )
    reader = _FakeAppointmentSnapshotReader(snapshot=snapshot)
    sync_use_case = _FakeSyncUseCase(record=_record(CalendarSyncStatus.OK))
    node = make_calendar_sync_node(
        object(), appointment_snapshot=reader, sync_use_case_factory=lambda conn, **kw: sync_use_case
    )
    state = _state(intent="schedule", role="reception", outcome=ActionOutcome(success=True, result_id="appt-1"))

    result = await node(state)

    assert result == {"calendar_sync_status": "ok"}
    assert sync_use_case.calls[0]["appointment_id"] == "appt-1"
    assert sync_use_case.calls[0]["site_id"] == "s1"


@pytest.mark.asyncio
async def test_emits_an_ungated_status_event_when_a_sync_is_attempted(monkeypatch) -> None:
    import app.platform.inbound.graph.nodes.calendar_sync as module

    calls: list[dict] = []
    monkeypatch.setattr(module, "emit_status", lambda **kw: calls.append(kw))
    snapshot = AppointmentSyncSnapshot(
        patient_id="p1", starts_at=datetime.now(timezone.utc), ends_at=datetime.now(timezone.utc), site_id="s1"
    )
    reader = _FakeAppointmentSnapshotReader(snapshot=snapshot)
    sync_use_case = _FakeSyncUseCase(record=_record(CalendarSyncStatus.OK))
    node = make_calendar_sync_node(
        object(), appointment_snapshot=reader, sync_use_case_factory=lambda conn, **kw: sync_use_case
    )
    state = _state(intent="schedule", role="reception", outcome=ActionOutcome(success=True, result_id="appt-1"))

    await node(state)

    assert len(calls) == 1
    assert calls[0].get("action") is None


@pytest.mark.asyncio
async def test_sync_failure_never_raises_and_reports_failed_status() -> None:
    snapshot = AppointmentSyncSnapshot(
        patient_id="p1", starts_at=datetime.now(timezone.utc), ends_at=datetime.now(timezone.utc), site_id="s1"
    )
    reader = _FakeAppointmentSnapshotReader(snapshot=snapshot)
    sync_use_case = _FakeSyncUseCase(record=_record(CalendarSyncStatus.FAILED))
    node = make_calendar_sync_node(
        object(), appointment_snapshot=reader, sync_use_case_factory=lambda conn, **kw: sync_use_case
    )
    state = _state(intent="schedule", role="reception", outcome=ActionOutcome(success=True, result_id="appt-1"))

    result = await node(state)

    assert result == {"calendar_sync_status": "failed"}


@pytest.mark.asyncio
async def test_not_applicable_when_outcome_missing() -> None:
    node = make_calendar_sync_node(object(), appointment_snapshot=None, sync_use_case_factory=None)
    state = _state(intent="schedule", role="reception", outcome=None)

    result = await node(state)

    assert result == {"calendar_sync_status": "n/a"}


@pytest.mark.asyncio
async def test_flagged_gap_patient_actor_has_no_staff_base_role_for_the_sync_write() -> None:
    node = make_calendar_sync_node(object(), appointment_snapshot=None, sync_use_case_factory=None)
    state = _state(intent="schedule", role="patient", outcome=ActionOutcome(success=True, result_id="appt-1"))

    result = await node(state)

    assert result == {"calendar_sync_status": "failed"}


@pytest.mark.asyncio
async def test_appointment_not_found_reports_failed() -> None:
    reader = _FakeAppointmentSnapshotReader(snapshot=None)
    node = make_calendar_sync_node(object(), appointment_snapshot=reader, sync_use_case_factory=None)
    state = _state(intent="schedule", role="reception", outcome=ActionOutcome(success=True, result_id="appt-1"))

    result = await node(state)

    assert result == {"calendar_sync_status": "failed"}
