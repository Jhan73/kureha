import pytest

from app.platform.inbound.graph.nodes.respond import make_respond_node
from app.platform.inbound.graph.ports.suggestion_generator import SuggestionCandidate
from app.platform.inbound.graph.state import ActionOutcome, KurehaState, ProposedAction, RequestContext


class _FakeSuggestionGenerator:
    def __init__(self, *, candidates: list[SuggestionCandidate]) -> None:
        self._candidates = candidates
        self.calls: list = []

    async def generate(self, ctx, *, context) -> list[SuggestionCandidate]:
        self.calls.append(context)
        return self._candidates


def _state(**overrides) -> KurehaState:
    base: KurehaState = {
        "request_ctx": RequestContext(tenant_id="t1", role="patient", patient_id="p1"),
        "channel": "patient_chat",
        "channel_message": "x",
        "intent": "schedule",
        "scope_ok": True,
        "consent_ok": True,
        "allowed_actions": ["appointment:create", "appointment:view"],
        "proposed_action": None,
        "rbac_ok": True,
        "risk_level": "low",
        "confirmation": "affirmed",
        "approval": None,
        "outcome": None,
        "audit_ref": None,
        "response_text": None,
        "response_scope_ok": True,
        "calendar_sync_status": None,
        "suggestions": None,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_passes_through_already_set_response_text_without_suggestions() -> None:
    generator = _FakeSuggestionGenerator(candidates=[])
    node = make_respond_node(generator)
    state = _state(response_text="Entendido, no realicé la acción.", intent="schedule")

    result = await node(state)

    assert result["response_text"] == "Entendido, no realicé la acción."
    assert result["suggestions"] is None
    assert generator.calls == []


@pytest.mark.asyncio
async def test_composes_from_outcome_when_response_text_unset() -> None:
    generator = _FakeSuggestionGenerator(candidates=[])
    node = make_respond_node(generator)
    action = ProposedAction(action="appointment:create", is_mutating=True, payload={}, summary="Cita agendada con la Dra. X")
    state = _state(response_text=None, proposed_action=action, outcome=ActionOutcome(success=True, result_id="appt-1"))

    result = await node(state)

    assert "Cita agendada con la Dra. X" in result["response_text"]


@pytest.mark.asyncio
async def test_generates_rbac_safe_suggestions_after_successful_schedule() -> None:
    candidates = [
        SuggestionCandidate(text="Agregar un recordatorio", action="appointment:view"),
        SuggestionCandidate(text="Cancelar una accion no permitida", action="staff:register"),
        SuggestionCandidate(text="Ver disponibilidad"),
    ]
    generator = _FakeSuggestionGenerator(candidates=candidates)
    node = make_respond_node(generator)
    action = ProposedAction(action="appointment:create", is_mutating=True, payload={}, summary="Cita agendada")
    state = _state(
        response_text=None,
        intent="schedule",
        proposed_action=action,
        outcome=ActionOutcome(success=True, result_id="appt-1"),
        allowed_actions=["appointment:create", "appointment:view"],
    )

    result = await node(state)

    assert result["suggestions"] == ["Agregar un recordatorio", "Ver disponibilidad"]
    assert "Cancelar una accion no permitida" not in result["response_text"]
    assert "Agregar un recordatorio" in result["response_text"]


@pytest.mark.asyncio
async def test_truncates_suggestions_to_three() -> None:
    candidates = [SuggestionCandidate(text=f"Sugerencia {i}") for i in range(5)]
    generator = _FakeSuggestionGenerator(candidates=candidates)
    node = make_respond_node(generator)
    action = ProposedAction(action="appointment:create", is_mutating=True, payload={}, summary="Cita agendada")
    state = _state(
        response_text=None,
        intent="schedule",
        proposed_action=action,
        outcome=ActionOutcome(success=True, result_id="appt-1"),
    )

    result = await node(state)

    assert len(result["suggestions"]) == 3


@pytest.mark.asyncio
async def test_no_suggestions_for_an_error_denial_response() -> None:
    generator = _FakeSuggestionGenerator(candidates=[SuggestionCandidate(text="should never be used")])
    node = make_respond_node(generator)
    state = _state(response_text="No tienes permiso para realizar esta accion.", intent="schedule")

    result = await node(state)

    assert result["suggestions"] is None
    assert generator.calls == []


@pytest.mark.asyncio
async def test_suggestions_justified_for_unknown_intent() -> None:
    generator = _FakeSuggestionGenerator(candidates=[SuggestionCandidate(text="Puedo ayudarte a agendar")])
    node = make_respond_node(generator)
    state = _state(response_text=None, intent="unknown", outcome=None, proposed_action=None)

    result = await node(state)

    assert result["suggestions"] == ["Puedo ayudarte a agendar"]


@pytest.mark.asyncio
async def test_clears_proposed_action_when_the_turn_concluded() -> None:
    generator = _FakeSuggestionGenerator(candidates=[])
    node = make_respond_node(generator)
    action = ProposedAction(action="appointment:create", is_mutating=True, payload={}, summary="Cita agendada")
    state = _state(
        response_text=None,
        confirmation="affirmed",
        proposed_action=action,
        outcome=ActionOutcome(success=True, result_id="appt-1"),
    )

    result = await node(state)

    assert result["proposed_action"] is None
    # Omitted, not forced to a value -- proves `respond` doesn't touch
    # `confirmation` at all (a real graph invocation would keep the
    # checkpoint's "affirmed" via LangGraph's default LastValue channel;
    # see test_build_graph.py's round-trip test for that merged-state proof).
    assert "confirmation" not in result


@pytest.mark.asyncio
async def test_preserves_proposed_action_when_confirmation_is_needed() -> None:
    generator = _FakeSuggestionGenerator(candidates=[])
    node = make_respond_node(generator)
    action = ProposedAction(action="appointment:create", is_mutating=True, payload={}, summary="Cita agendada")
    state = _state(
        response_text="Voy a agendar tu cita. ¿Confirmas?",
        confirmation="needed",
        proposed_action=action,
        outcome=None,
    )

    result = await node(state)

    assert result["proposed_action"] is action
