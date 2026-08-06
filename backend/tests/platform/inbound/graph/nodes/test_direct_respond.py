import pytest

from app.platform.inbound.graph.nodes.direct_respond import make_direct_respond_node
from app.platform.inbound.graph.ports.direct_response import DirectResponsePlan
from app.platform.inbound.graph.state import KurehaState, RequestContext


class _FakeDirectResponse:
    def __init__(self, *, text: str) -> None:
        self._text = text
        self.calls: list[tuple[str, str, str, list[str] | None]] = []

    async def respond(self, ctx, *, intent: str, message: str, allowed_actions) -> DirectResponsePlan:
        self.calls.append((ctx.tenant_id, intent, message, allowed_actions))
        return DirectResponsePlan(text=self._text)


def _state(*, intent: str, allowed_actions: list[str] | None = None) -> KurehaState:
    return {
        "request_ctx": RequestContext(tenant_id="t1", role="patient", patient_id="p1"),
        "channel": "patient_chat",
        "channel_message": "hola",
        "intent": intent,
        "scope_ok": None,
        "consent_ok": None,
        "allowed_actions": allowed_actions,
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
async def test_delegates_to_direct_response_port_and_sets_response_text() -> None:
    port = _FakeDirectResponse(text="Hola! Soy Tony.")
    node = make_direct_respond_node(port)
    state = _state(intent="greeting", allowed_actions=["appointment:create"])

    result = await node(state)

    assert result == {"response_text": "Hola! Soy Tony."}
    assert port.calls == [("t1", "greeting", "hola", ["appointment:create"])]
