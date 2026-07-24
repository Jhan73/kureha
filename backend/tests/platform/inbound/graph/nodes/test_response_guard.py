"""Task 11.5: `response_guard` node -- outbound `ClinicalScopePolicy.
classify_outbound`, non-streaming single-shot for this batch."""

import pytest

from app.modules.governance.scope.domain.scope_policy import OutboundScopeCategory, OutboundScopeResult
from app.platform.inbound.graph.nodes.response_guard import make_response_guard_node
from app.platform.inbound.graph.state import KurehaState, RequestContext


class _FakeScopePolicy:
    def __init__(self, *, category: OutboundScopeCategory) -> None:
        self._category = category
        self.classified_chunks: list[str] = []

    async def classify_inbound(self, ctx, message: str):
        raise NotImplementedError

    async def classify_outbound(self, ctx, chunk: str) -> OutboundScopeResult:
        self.classified_chunks.append(chunk)
        return OutboundScopeResult(category=self._category, should_block=self._category is not OutboundScopeCategory.SAFE)


def _state(*, response_text: str | None) -> KurehaState:
    return {
        "request_ctx": RequestContext(tenant_id="t1", role="patient", patient_id="p1"),
        "channel": "patient_chat",
        "channel_message": "x",
        "intent": "schedule",
        "scope_ok": True,
        "consent_ok": True,
        "allowed_actions": None,
        "proposed_action": None,
        "rbac_ok": None,
        "risk_level": None,
        "confirmation": None,
        "approval": None,
        "outcome": None,
        "audit_ref": None,
        "response_text": response_text,
        "response_scope_ok": None,
        "calendar_sync_status": None,
        "suggestions": None,
    }


@pytest.mark.asyncio
async def test_safe_response_sets_response_scope_ok_true() -> None:
    policy = _FakeScopePolicy(category=OutboundScopeCategory.SAFE)
    node = make_response_guard_node(policy)
    state = _state(response_text="Tu cita fue agendada.")

    result = await node(state)

    assert result == {"response_scope_ok": True}
    assert policy.classified_chunks == ["Tu cita fue agendada."]


@pytest.mark.asyncio
async def test_clinical_content_sets_response_scope_ok_false() -> None:
    policy = _FakeScopePolicy(category=OutboundScopeCategory.CLINICAL_CONTENT)
    node = make_response_guard_node(policy)
    state = _state(response_text="Deberias tomar ibuprofeno.")

    result = await node(state)

    assert result == {"response_scope_ok": False}


@pytest.mark.asyncio
async def test_none_response_text_classifies_empty_string() -> None:
    """Operational path -- `respond` has not composed text yet at this
    point (see this node's own docstring)."""
    policy = _FakeScopePolicy(category=OutboundScopeCategory.SAFE)
    node = make_response_guard_node(policy)
    state = _state(response_text=None)

    result = await node(state)

    assert result == {"response_scope_ok": True}
    assert policy.classified_chunks == [""]
