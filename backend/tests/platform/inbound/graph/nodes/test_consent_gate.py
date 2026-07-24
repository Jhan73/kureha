"""Task 11.2: `consent_gate` node -- delegates to `CheckConsent` for
patient-touching intents; bypasses to `consent_ok=True` for `staff`/`shift`
(design.md §8.3's note right after the edges diagram)."""

import pytest

from app.modules.governance.consent.domain.consent_policy import ConsentCheckResult
from app.platform.inbound.graph.nodes.consent_gate import make_consent_gate_node
from app.platform.inbound.graph.state import KurehaState, RequestContext


class _FakeCheckConsent:
    def __init__(self, *, result: ConsentCheckResult) -> None:
        self._result = result
        self.calls: list[tuple[str, str]] = []

    async def execute(self, ctx, *, patient_id: str) -> ConsentCheckResult:
        self.calls.append((ctx.tenant_id, patient_id))
        return self._result


def _state(*, intent: str, patient_id: str | None) -> KurehaState:
    return {
        "request_ctx": RequestContext(tenant_id="t1", role="patient", patient_id=patient_id),
        "channel": "patient_chat",
        "channel_message": "x",
        "intent": intent,
        "scope_ok": True,
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
async def test_staff_intent_bypasses_consent_check() -> None:
    check_consent = _FakeCheckConsent(result=ConsentCheckResult.MISSING)
    node = make_consent_gate_node(check_consent)

    result = await node(_state(intent="staff", patient_id=None))

    assert result == {"consent_ok": True}
    assert check_consent.calls == []


@pytest.mark.asyncio
async def test_shift_intent_bypasses_consent_check() -> None:
    check_consent = _FakeCheckConsent(result=ConsentCheckResult.MISSING)
    node = make_consent_gate_node(check_consent)

    result = await node(_state(intent="shift", patient_id=None))

    assert result == {"consent_ok": True}
    assert check_consent.calls == []


@pytest.mark.asyncio
async def test_schedule_intent_with_current_consent_is_ok() -> None:
    check_consent = _FakeCheckConsent(result=ConsentCheckResult.CURRENT)
    node = make_consent_gate_node(check_consent)

    result = await node(_state(intent="schedule", patient_id="p1"))

    assert result == {"consent_ok": True}
    assert check_consent.calls == [("t1", "p1")]


@pytest.mark.asyncio
async def test_schedule_intent_with_missing_consent_denies() -> None:
    check_consent = _FakeCheckConsent(result=ConsentCheckResult.MISSING)
    node = make_consent_gate_node(check_consent)

    result = await node(_state(intent="schedule", patient_id="p1"))

    assert result == {"consent_ok": False}


@pytest.mark.asyncio
async def test_schedule_intent_with_outdated_consent_denies() -> None:
    check_consent = _FakeCheckConsent(result=ConsentCheckResult.OUTDATED)
    node = make_consent_gate_node(check_consent)

    result = await node(_state(intent="schedule", patient_id="p1"))

    assert result == {"consent_ok": False}


@pytest.mark.asyncio
async def test_patient_touching_intent_without_a_patient_id_denies_without_calling_check_consent() -> None:
    """Deny-by-default when `request_ctx.patient_id` is unresolved -- see
    the node's own module docstring for the flagged staff-copilot-on-behalf-
    of-a-patient gap this guards against."""
    check_consent = _FakeCheckConsent(result=ConsentCheckResult.CURRENT)
    node = make_consent_gate_node(check_consent)

    result = await node(_state(intent="schedule", patient_id=None))

    assert result == {"consent_ok": False}
    assert check_consent.calls == []
