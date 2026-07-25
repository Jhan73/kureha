"""tasks.md task 12.7 (PR 12 batch 2): `AnthropicReminderPlanner`, the real
`ReminderPlannerPort` adapter `reminders_agent` consumes (design.md §8.10:
"Tarea simple: generar texto de recordatorio parametrico"). Fast tier."""

import pytest

from app.platform.inbound.graph.adapters.anthropic_reminder_planner import AnthropicReminderPlanner
from app.shared_kernel.tenant_context import TenantContext

_CTX = TenantContext(tenant_id="tenant-1", role="patient")


class _FakeStructuredRunnable:
    def __init__(self, result_or_exc) -> None:
        self._result_or_exc = result_or_exc
        self.calls: list[list] = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        if isinstance(self._result_or_exc, BaseException):
            raise self._result_or_exc
        return self._result_or_exc


class _FakeChatModel:
    def __init__(self, result_or_exc) -> None:
        self._result_or_exc = result_or_exc
        self.runnable: _FakeStructuredRunnable | None = None

    def with_structured_output(self, schema, **kwargs):
        self.runnable = _FakeStructuredRunnable(self._result_or_exc)
        return self.runnable


class _Extraction:
    def __init__(self, appointment_id: str | None = None, summary: str = "") -> None:
        self.appointment_id = appointment_id
        self.summary = summary


async def test_plan_returns_the_extracted_appointment_id_and_summary() -> None:
    llm = _FakeChatModel(_Extraction(appointment_id="appt-1", summary="Recordatorio para tu cita del martes."))
    planner = AnthropicReminderPlanner(llm)

    plan = await planner.plan(_CTX, message="mandame un recordatorio para appt-1")

    assert plan.appointment_id == "appt-1"
    assert plan.summary == "Recordatorio para tu cita del martes."


async def test_plan_returns_an_empty_string_id_never_none_or_a_fabricated_id_when_unresolved() -> None:
    """Free conversational text ("my Tuesday appointment") gives the model no
    real way to resolve a UUID -- `ReminderPlan.appointment_id: str` has no
    `| None` in its own type, so this must be a type-correct, OBVIOUSLY
    invalid placeholder (`""`), never a plausible-looking fabricated id that
    could silently match the wrong appointment."""
    llm = _FakeChatModel(_Extraction(appointment_id=None, summary="Recordatorio para tu proxima cita."))
    planner = AnthropicReminderPlanner(llm)

    plan = await planner.plan(_CTX, message="mandame un recordatorio de mi cita del martes")

    assert plan.appointment_id == ""


async def test_message_reaches_the_model() -> None:
    llm = _FakeChatModel(_Extraction(appointment_id="appt-1", summary="Recordatorio."))
    planner = AnthropicReminderPlanner(llm)

    await planner.plan(_CTX, message="recuerdame la cita appt-1 de mañana")

    assert llm.runnable is not None
    sent = llm.runnable.calls[0]
    assert any("recuerdame la cita appt-1 de mañana" in str(m.content) for m in sent)


async def test_an_llm_failure_propagates_no_try_except_here() -> None:
    llm = _FakeChatModel(RuntimeError("boom"))
    planner = AnthropicReminderPlanner(llm)

    with pytest.raises(RuntimeError, match="boom"):
        await planner.plan(_CTX, message="algo")
