import pytest

from app.platform.inbound.graph.nodes.triage import make_triage_node
from app.platform.inbound.graph.ports.intent_classifier import IntentClassificationResult
from app.platform.inbound.graph.state import KurehaState, RequestContext


class _FakeClassifier:
    def __init__(self, *, intent: str) -> None:
        self._intent = intent
        self.calls: list[tuple[str, str]] = []

    async def classify(self, ctx, message: str) -> IntentClassificationResult:
        self.calls.append((ctx.tenant_id, message))
        return IntentClassificationResult(intent=self._intent)


def _state(message: str = "Quiero agendar una cita") -> KurehaState:
    return {
        "request_ctx": RequestContext(tenant_id="t1", role="patient", patient_id="p1"),
        "channel": "patient_chat",
        "channel_message": message,
        "intent": None,
        "scope_ok": None,
        "consent_ok": None,
        "allowed_actions": None,
        "proposed_action": None,
        "rbac_ok": None,
        "risk_level": None,
        "confirmation": None,
        "approval": None,
        "outcome": None,
        "audit_ref": None,
        "response_text": None,
        "response_scope_ok": None,
        "calendar_sync_status": None,
        "suggestions": None,
    }


@pytest.mark.asyncio
async def test_triage_sets_intent_from_the_classifier_verdict() -> None:
    classifier = _FakeClassifier(intent="schedule")
    node = make_triage_node(classifier)

    result = await node(_state())

    assert result == {"intent": "schedule"}


@pytest.mark.asyncio
async def test_triage_passes_the_tenant_context_and_message_to_the_classifier() -> None:
    classifier = _FakeClassifier(intent="greeting")
    node = make_triage_node(classifier)

    await node(_state("hola"))

    assert classifier.calls == [("t1", "hola")]
