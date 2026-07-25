"""tasks.md task 12.7 (PR 12 batch 2): `AnthropicStaffPlanner`, the real
`StaffPlannerPort` adapter `staff_agent` consumes (design.md §8.10).
Reasoner tier. Same ID-resolution-gap posture as `AnthropicSchedulingPlanner`
-- see that module's own docstring for the full explanation; not repeated
here at length."""

import pytest

from app.platform.inbound.graph.adapters.anthropic_staff_planner import AnthropicStaffPlanner
from app.shared_kernel.tenant_context import TenantContext

_CTX = TenantContext(tenant_id="tenant-1", role="admin")


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
    def __init__(self, results: dict[type, object]) -> None:
        self._results = results
        self.bound_schemas: list[type] = []
        self.runnables: dict[type, _FakeStructuredRunnable] = {}

    def with_structured_output(self, schema, **kwargs):
        self.bound_schemas.append(schema)
        runnable = _FakeStructuredRunnable(self._results[schema])
        self.runnables[schema] = runnable
        return runnable


class _StaffExtraction:
    def __init__(self, **fields) -> None:
        self.action = fields["action"]
        self.site_id = fields.get("site_id")
        self.name = fields.get("name")
        self.operational_role = fields.get("operational_role")
        self.user_id = fields.get("user_id")
        self.professional_id = fields.get("professional_id")
        self.staff_member_id = fields.get("staff_member_id")
        self.summary = fields.get("summary", "")


class _ShiftExtraction:
    def __init__(self, **fields) -> None:
        self.action = fields["action"]
        self.site_id = fields.get("site_id")
        self.staff_member_id = fields.get("staff_member_id")
        self.shift_id = fields.get("shift_id")
        self.starts_at = fields.get("starts_at")
        self.ends_at = fields.get("ends_at")
        self.summary = fields.get("summary", "")


def _planner_for_staff(extraction: _StaffExtraction) -> tuple[AnthropicStaffPlanner, _FakeChatModel]:
    from app.platform.inbound.graph.adapters.anthropic_staff_planner import _StaffAction

    llm = _FakeChatModel({_StaffAction: extraction})
    return AnthropicStaffPlanner(llm), llm


def _planner_for_shift(extraction: _ShiftExtraction) -> tuple[AnthropicStaffPlanner, _FakeChatModel]:
    from app.platform.inbound.graph.adapters.anthropic_staff_planner import _ShiftAction

    llm = _FakeChatModel({_ShiftAction: extraction})
    return AnthropicStaffPlanner(llm), llm


async def test_staff_intent_lets_the_model_choose_between_register_and_deactivate() -> None:
    extraction = _StaffExtraction(action="staff:deactivate", staff_member_id="staff-1", summary="Da de baja a X.")
    planner, _ = _planner_for_staff(extraction)

    plan = await planner.plan(_CTX, intent="staff", message="da de baja a Juan Perez")

    assert plan.action == "staff:deactivate"
    assert plan.kwargs == {"staff_member_id": "staff-1"}


async def test_staff_register_kwargs_only_include_extracted_fields() -> None:
    extraction = _StaffExtraction(
        action="staff:register", name="Maria Lopez", operational_role="reception", summary="Registra a Maria."
    )
    planner, _ = _planner_for_staff(extraction)

    plan = await planner.plan(_CTX, intent="staff", message="registra a Maria Lopez como recepcion")

    assert plan.kwargs == {"name": "Maria Lopez", "operational_role": "reception"}


async def test_staff_kwargs_are_empty_when_the_model_extracts_nothing() -> None:
    extraction = _StaffExtraction(action="staff:register", summary="Registra un nuevo staff.")
    planner, _ = _planner_for_staff(extraction)

    plan = await planner.plan(_CTX, intent="staff", message="quiero registrar personal nuevo")

    assert plan.kwargs == {}


async def test_shift_intent_lets_the_model_choose_between_create_and_edit() -> None:
    extraction = _ShiftExtraction(action="shift:edit", shift_id="shift-1", summary="Edita el turno.")
    planner, _ = _planner_for_shift(extraction)

    plan = await planner.plan(_CTX, intent="shift", message="cambia mi turno de mañana")

    assert plan.action == "shift:edit"
    assert plan.kwargs == {"shift_id": "shift-1"}


async def test_shift_create_kwargs_parse_starts_at_and_ends_at_into_datetimes() -> None:
    from datetime import datetime

    extraction = _ShiftExtraction(
        action="shift:create",
        staff_member_id="staff-1",
        starts_at="2026-08-01T08:00:00+00:00",
        ends_at="2026-08-01T17:00:00+00:00",
        summary="Crea un turno.",
    )
    planner, _ = _planner_for_shift(extraction)

    plan = await planner.plan(_CTX, intent="shift", message="crea un turno para staff-1 de 8 a 5")

    assert plan.kwargs["staff_member_id"] == "staff-1"
    assert plan.kwargs["starts_at"] == datetime.fromisoformat("2026-08-01T08:00:00+00:00")
    assert plan.kwargs["ends_at"] == datetime.fromisoformat("2026-08-01T17:00:00+00:00")


async def test_shift_kwargs_drop_an_unparseable_datetime_instead_of_raising() -> None:
    """A malformed ISO string from the model is a data-shape problem, not an
    infra failure -- dropping the key (same "omit, never fabricate" posture
    as every other unresolved ID field) is safer than crashing before this
    node even reaches `rbac_gate`."""
    extraction = _ShiftExtraction(
        action="shift:create", staff_member_id="staff-1", starts_at="not-a-date", summary="Crea un turno."
    )
    planner, _ = _planner_for_shift(extraction)

    plan = await planner.plan(_CTX, intent="shift", message="crea un turno mañana")

    assert "starts_at" not in plan.kwargs
    assert plan.kwargs == {"staff_member_id": "staff-1"}


async def test_message_reaches_the_model() -> None:
    extraction = _StaffExtraction(action="staff:register", summary="Registra personal.")
    planner, llm = _planner_for_staff(extraction)

    await planner.plan(_CTX, intent="staff", message="registra a Carlos Mendez como profesional")

    from app.platform.inbound.graph.adapters.anthropic_staff_planner import _StaffAction

    sent = llm.runnables[_StaffAction].calls[0]
    assert any("registra a Carlos Mendez como profesional" in str(m.content) for m in sent)


async def test_an_llm_failure_propagates_no_try_except_here() -> None:
    from app.platform.inbound.graph.adapters.anthropic_staff_planner import _StaffAction

    llm = _FakeChatModel({_StaffAction: RuntimeError("boom")})
    planner = AnthropicStaffPlanner(llm)

    with pytest.raises(RuntimeError, match="boom"):
        await planner.plan(_CTX, intent="staff", message="algo")


async def test_unsupported_intent_raises_instead_of_guessing_an_action() -> None:
    planner = AnthropicStaffPlanner(_FakeChatModel({}))

    with pytest.raises(ValueError, match="schedule"):
        await planner.plan(_CTX, intent="schedule", message="algo")
