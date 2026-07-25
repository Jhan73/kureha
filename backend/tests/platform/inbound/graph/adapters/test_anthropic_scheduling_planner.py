"""tasks.md task 12.7 (PR 12 batch 2): `AnthropicSchedulingPlanner`, the real
`SchedulingPlannerPort` adapter `scheduling_agent` consumes (design.md
§8.4 point 1/§8.10). Reasoner tier. No real network -- same hand-rolled
fake-chat-model precedent as `test_anthropic_intent_classifier.py`.

**The dominant thing these tests prove is the ID-resolution gap this
adapter's own module docstring flags at length: `kwargs` only ever contains
fields the model actually extracted (never a fabricated ID), and any field
it did not extract is simply ABSENT from `kwargs` (never `None`) so
`persist_and_audit`'s `use_case.execute(ctx, **payload)` fails LOUDLY with a
clean `TypeError` for a missing required kwarg, rather than passing a
literal `None` into a use case that has no way to safely handle it.**"""

import pytest

from app.platform.inbound.graph.adapters.anthropic_scheduling_planner import AnthropicSchedulingPlanner
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
        self.bound_schemas: list[type] = []
        self.runnable: _FakeStructuredRunnable | None = None

    def with_structured_output(self, schema, **kwargs):
        self.bound_schemas.append(schema)
        self.runnable = _FakeStructuredRunnable(self._result_or_exc)
        return self.runnable


class _Extraction:
    def __init__(self, **fields) -> None:
        self.patient_id = fields.get("patient_id")
        self.professional_id = fields.get("professional_id")
        self.site_id = fields.get("site_id")
        self.availability_id = fields.get("availability_id")
        self.appointment_id = fields.get("appointment_id")
        self.new_availability_id = fields.get("new_availability_id")
        self.appointment_ids = fields.get("appointment_ids")
        self.requested_professional_id = fields.get("requested_professional_id")
        self.target_professional_id = fields.get("target_professional_id")
        self.summary = fields.get("summary", "")


async def test_schedule_intent_maps_deterministically_to_appointment_create() -> None:
    """`action` is derived from `intent` deterministically -- `intent` was
    already validated upstream by `triage`'s own Literal enum, so the LLM is
    never asked to re-guess it."""
    llm = _FakeChatModel(_Extraction(summary="Agenda una cita."))
    planner = AnthropicSchedulingPlanner(llm)

    plan = await planner.plan(_CTX, intent="schedule", message="quiero una cita")

    assert plan.action == "appointment:create"


async def test_reschedule_intent_maps_to_appointment_reschedule() -> None:
    llm = _FakeChatModel(_Extraction(summary="Reprograma una cita."))
    planner = AnthropicSchedulingPlanner(llm)

    plan = await planner.plan(_CTX, intent="reschedule", message="quiero cambiar mi cita")

    assert plan.action == "appointment:reschedule"


async def test_cancel_intent_maps_to_appointment_cancel() -> None:
    llm = _FakeChatModel(_Extraction(summary="Cancela una cita."))
    planner = AnthropicSchedulingPlanner(llm)

    plan = await planner.plan(_CTX, intent="cancel", message="quiero cancelar mi cita")

    assert plan.action == "appointment:cancel"


async def test_schedule_kwargs_only_include_fields_the_model_actually_extracted() -> None:
    """No real IDs exist in typical conversational text -- when the model
    extracts nothing, `kwargs` must be EMPTY, never populated with `None`
    placeholders (that would let a `None` silently reach the real use
    case's SQL layer instead of failing loudly with a clean `TypeError`)."""
    llm = _FakeChatModel(_Extraction(summary="Agenda una cita el martes."))
    planner = AnthropicSchedulingPlanner(llm)

    plan = await planner.plan(_CTX, intent="schedule", message="quiero una cita el martes")

    assert plan.kwargs == {}
    assert None not in plan.kwargs.values()


async def test_schedule_kwargs_include_only_extracted_fields_when_partially_known() -> None:
    llm = _FakeChatModel(_Extraction(patient_id="patient-123", summary="Agenda para el paciente 123."))
    planner = AnthropicSchedulingPlanner(llm)

    plan = await planner.plan(_CTX, intent="schedule", message="agenda al paciente patient-123")

    assert plan.kwargs == {"patient_id": "patient-123"}


async def test_reschedule_kwargs_only_carry_reschedule_shaped_fields() -> None:
    """A field irrelevant to `RescheduleAppointment.execute`'s own kwargs
    shape (e.g. `patient_id`) must never leak into `kwargs` even if the
    model extracted it for some other reason."""
    llm = _FakeChatModel(
        _Extraction(
            appointment_id="appt-1",
            new_availability_id="avail-2",
            patient_id="patient-999",
            summary="Reprograma la cita appt-1.",
        )
    )
    planner = AnthropicSchedulingPlanner(llm)

    plan = await planner.plan(_CTX, intent="reschedule", message="reprograma mi cita appt-1 a avail-2")

    assert plan.kwargs == {"appointment_id": "appt-1", "new_availability_id": "avail-2"}


async def test_cancel_kwargs_only_carry_appointment_id() -> None:
    llm = _FakeChatModel(
        _Extraction(appointment_id="appt-1", appointment_ids=["appt-1"], summary="Cancela la cita appt-1.")
    )
    planner = AnthropicSchedulingPlanner(llm)

    plan = await planner.plan(_CTX, intent="cancel", message="cancela mi cita appt-1")

    assert plan.kwargs == {"appointment_id": "appt-1"}


async def test_bulk_cancel_risk_fields_survive_into_the_plan_but_never_into_kwargs() -> None:
    """`appointment_ids`/`requested_professional_id`/`target_professional_id`
    exist SOLELY to feed `scheduling_agent`'s `RiskPolicy` calls
    (`SchedulingPlannerPort`'s own docstring) -- they must be readable on the
    `SchedulingPlan` itself but never dispatched to `CancelAppointment.
    execute()`, which has no such kwarg."""
    llm = _FakeChatModel(
        _Extraction(
            appointment_id="appt-1",
            appointment_ids=["appt-1", "appt-2", "appt-3", "appt-4"],
            summary="Cancela todas mis citas del martes.",
        )
    )
    planner = AnthropicSchedulingPlanner(llm)

    plan = await planner.plan(_CTX, intent="cancel", message="cancela todas mis citas del martes")

    assert plan.appointment_ids == ["appt-1", "appt-2", "appt-3", "appt-4"]
    assert "appointment_ids" not in plan.kwargs


async def test_reschedule_risk_fields_survive_into_the_plan_but_never_into_kwargs() -> None:
    llm = _FakeChatModel(
        _Extraction(
            appointment_id="appt-1",
            new_availability_id="avail-2",
            requested_professional_id="prof-requested",
            target_professional_id="prof-target",
            summary="Reprograma con otro profesional.",
        )
    )
    planner = AnthropicSchedulingPlanner(llm)

    plan = await planner.plan(_CTX, intent="reschedule", message="cambia mi cita a otro profesional")

    assert plan.requested_professional_id == "prof-requested"
    assert plan.target_professional_id == "prof-target"
    assert "requested_professional_id" not in plan.kwargs
    assert "target_professional_id" not in plan.kwargs


async def test_summary_is_always_carried_for_the_confirmation_prompt() -> None:
    llm = _FakeChatModel(_Extraction(summary="Agenda una cita el martes a las 10am."))
    planner = AnthropicSchedulingPlanner(llm)

    plan = await planner.plan(_CTX, intent="schedule", message="quiero una cita el martes a las 10am")

    assert plan.summary == "Agenda una cita el martes a las 10am."


async def test_message_reaches_the_model() -> None:
    llm = _FakeChatModel(_Extraction(summary="Agenda una cita."))
    planner = AnthropicSchedulingPlanner(llm)

    await planner.plan(_CTX, intent="schedule", message="quiero una cita para el jueves con la Dra. Vega")

    assert llm.runnable is not None
    sent = llm.runnable.calls[0]
    assert any("quiero una cita para el jueves con la Dra. Vega" in str(m.content) for m in sent)


async def test_an_llm_failure_propagates_no_try_except_here() -> None:
    """Mirrors `persist_and_audit`'s own "no try/except, propagate to the
    central error handler" posture (its own module docstring) -- unlike the
    classifiers built in batch 1, a planner has no safe "unknown"-shaped
    fallback value it could resolve to instead: `scheduling_agent`'s only
    outgoing edge is an UNCONDITIONAL `add_edge("scheduling_agent",
    "rbac_gate")` (`build_graph.py`), there is no designed failure-routing
    edge this node could redirect to on a planner error."""
    llm = _FakeChatModel(RuntimeError("boom"))
    planner = AnthropicSchedulingPlanner(llm)

    with pytest.raises(RuntimeError, match="boom"):
        await planner.plan(_CTX, intent="schedule", message="algo")


async def test_unsupported_intent_raises_instead_of_guessing_an_action() -> None:
    llm = _FakeChatModel(_Extraction(summary="n/a"))
    planner = AnthropicSchedulingPlanner(llm)

    with pytest.raises(ValueError, match="staff"):
        await planner.plan(_CTX, intent="staff", message="algo")
