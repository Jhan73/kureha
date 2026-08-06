import pytest

from app.platform.inbound.graph.nodes.confirmation_gate import make_confirmation_gate_node
from app.platform.inbound.graph.ports.affirmation_classifier import AffirmationResult
from app.platform.inbound.graph.state import KurehaState, ProposedAction, RequestContext


class _FakeAffirmationClassifier:
    def __init__(self, *, decision: str) -> None:
        self._decision = decision
        self.calls: list[tuple[str, str, str]] = []

    async def classify(self, ctx, message: str, *, pending_action_summary: str) -> AffirmationResult:
        self.calls.append((ctx.tenant_id, message, pending_action_summary))
        return AffirmationResult(decision=self._decision)


class _ExplodingAffirmationClassifier:
    """Used to prove `not_required` branches never reach the classifier."""

    async def classify(self, ctx, message: str, *, pending_action_summary: str) -> AffirmationResult:
        raise AssertionError("AffirmationClassifierPort must not be called on a not_required branch")


def _state(*, channel: str, proposed_action: ProposedAction | None, message: str = "hola") -> KurehaState:
    return {
        "request_ctx": RequestContext(tenant_id="t1", role="patient", patient_id="p1"),
        "channel": channel,
        "channel_message": message,
        "intent": "schedule",
        "scope_ok": True,
        "consent_ok": True,
        "allowed_actions": None,
        "proposed_action": proposed_action,
        "rbac_ok": True,
        "risk_level": "low",
        "confirmation": None,
        "approval": None,
        "outcome": None,
        "audit_ref": None,
        "response_text": None,
        "response_scope_ok": None,
        "calendar_sync_status": None,
        "suggestions": None,
    }


def _proposed_action(*, is_mutating: bool = True, summary: str = "Voy a reservar una cita con la Dra. X el martes 10:00.") -> ProposedAction:
    return ProposedAction(action="appointment:create", is_mutating=is_mutating, payload={}, summary=summary)


@pytest.mark.asyncio
async def test_not_required_when_channel_is_web_form() -> None:
    node = make_confirmation_gate_node(_ExplodingAffirmationClassifier())  # type: ignore[arg-type]
    action = _proposed_action()
    state = _state(channel="web_form", proposed_action=action)

    result = await node(state)

    assert result == {"confirmation": "not_required", "proposed_action": action}


@pytest.mark.asyncio
async def test_not_required_when_action_is_not_mutating() -> None:
    node = make_confirmation_gate_node(_ExplodingAffirmationClassifier())  # type: ignore[arg-type]
    action = _proposed_action(is_mutating=False)
    state = _state(channel="patient_chat", proposed_action=action)

    result = await node(state)

    assert result == {"confirmation": "not_required", "proposed_action": action}


@pytest.mark.asyncio
async def test_defensive_guard_when_no_proposed_action() -> None:
    node = make_confirmation_gate_node(_ExplodingAffirmationClassifier())  # type: ignore[arg-type]
    state = _state(channel="patient_chat", proposed_action=None)

    result = await node(state)

    assert result == {"confirmation": "not_required", "proposed_action": None}


@pytest.mark.asyncio
async def test_needed_when_classifier_returns_unclear_and_builds_prompt_from_summary() -> None:
    classifier = _FakeAffirmationClassifier(decision="unclear")
    node = make_confirmation_gate_node(classifier)
    action = _proposed_action(summary="Voy a reservar una cita con la Dra. X el martes 10:00.")
    state = _state(channel="patient_chat", proposed_action=action, message="quiero agendar una cita")

    result = await node(state)

    assert result["confirmation"] == "needed"
    assert result["proposed_action"] == action
    assert result["response_text"] == "Voy a reservar una cita con la Dra. X el martes 10:00. ¿Confirmas?"
    assert classifier.calls == [("t1", "quiero agendar una cita", action.summary)]


@pytest.mark.asyncio
async def test_affirmed_when_classifier_returns_affirmed_and_keeps_proposed_action() -> None:
    classifier = _FakeAffirmationClassifier(decision="affirmed")
    node = make_confirmation_gate_node(classifier)
    action = _proposed_action()
    state = _state(channel="patient_chat", proposed_action=action, message="sí, confirmo")

    result = await node(state)

    assert result == {"confirmation": "affirmed", "proposed_action": action}


@pytest.mark.asyncio
async def test_unclear_on_first_pass_asks_needed_not_regressed() -> None:
    classifier = _FakeAffirmationClassifier(decision="unclear")
    node = make_confirmation_gate_node(classifier)
    action = _proposed_action()
    state = _state(channel="patient_chat", proposed_action=action, message="che, otra cosa")
    state["confirmation"] = None

    result = await node(state)

    assert result["confirmation"] == "needed"
    assert result["proposed_action"] == action


@pytest.mark.asyncio
async def test_unclear_on_reply_pass_declines_and_cleans_checkpoint() -> None:
    classifier = _FakeAffirmationClassifier(decision="unclear")
    node = make_confirmation_gate_node(classifier)
    action = _proposed_action()
    state = _state(channel="patient_chat", proposed_action=action, message="che, hablemos de otra cosa")
    state["confirmation"] = "needed"

    result = await node(state)

    assert "proposed_action" in result
    assert result["proposed_action"] is None
    assert "confirmation" in result
    assert result["confirmation"] is None
    assert result["response_text"]


@pytest.mark.asyncio
async def test_decline_explicitly_clears_proposed_action_and_confirmation() -> None:
    classifier = _FakeAffirmationClassifier(decision="declined")
    node = make_confirmation_gate_node(classifier)
    action = _proposed_action()
    state = _state(channel="staff_copilot", proposed_action=action, message="no, dejalo")

    result = await node(state)

    assert "proposed_action" in result
    assert result["proposed_action"] is None
    assert "confirmation" in result
    assert result["confirmation"] is None
    assert result["response_text"]
