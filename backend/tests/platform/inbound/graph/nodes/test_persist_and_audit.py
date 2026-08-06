import pytest

from app.platform.inbound.graph.nodes.persist_and_audit import UnroutableActionError, make_persist_and_audit_node
from app.platform.inbound.graph.state import KurehaState, ProposedAction, RequestContext


class _FakeResultWithId:
    def __init__(self, id: str) -> None:
        self.id = id


class _FakeUseCase:
    def __init__(self, *, result) -> None:
        self._result = result
        self.calls: list[tuple] = []

    async def execute(self, ctx, **kwargs):
        self.calls.append((ctx, kwargs))
        return self._result


def _state(*, proposed_action: ProposedAction) -> KurehaState:
    return {
        "request_ctx": RequestContext(tenant_id="t1", role="reception", site_id="s1", user_id="u1"),
        "channel": "staff_copilot",
        "channel_message": "x",
        "intent": "schedule",
        "scope_ok": True,
        "consent_ok": True,
        "allowed_actions": None,
        "proposed_action": proposed_action,
        "rbac_ok": True,
        "risk_level": "low",
        "confirmation": "affirmed",
        "approval": None,
        "outcome": None,
        "audit_ref": None,
        "response_text": None,
        "response_scope_ok": None,
        "calendar_sync_status": None,
        "suggestions": None,
    }


@pytest.mark.asyncio
async def test_dispatches_to_the_matching_use_case_with_payload_as_kwargs() -> None:
    use_case = _FakeUseCase(result=_FakeResultWithId("appt-1"))
    dispatch = {"appointment:create": lambda conn: use_case}
    node = make_persist_and_audit_node(object(), dispatch=dispatch)
    action = ProposedAction(
        action="appointment:create",
        is_mutating=True,
        payload={"patient_id": "p1", "professional_id": "pr1", "site_id": "s1", "availability_id": "a1"},
        summary="s",
    )
    state = _state(proposed_action=action)

    result = await node(state)

    assert result["outcome"].success is True
    assert result["outcome"].result_id == "appt-1"
    assert use_case.calls[0][1] == {
        "patient_id": "p1",
        "professional_id": "pr1",
        "site_id": "s1",
        "availability_id": "a1",
    }


@pytest.mark.asyncio
async def test_captures_result_with_no_id_attribute_as_none() -> None:
    use_case = _FakeUseCase(result=True)
    dispatch = {"appointment:view": lambda conn: use_case}
    node = make_persist_and_audit_node(object(), dispatch=dispatch)
    action = ProposedAction(action="appointment:view", is_mutating=True, payload={"appointment_id": "appt-1"}, summary="s")
    state = _state(proposed_action=action)

    result = await node(state)

    assert result["outcome"].success is True
    assert result["outcome"].result_id is None


@pytest.mark.asyncio
async def test_unroutable_action_raises() -> None:
    node = make_persist_and_audit_node(object(), dispatch={})
    action = ProposedAction(action="appointment:create", is_mutating=True, payload={}, summary="s")
    state = _state(proposed_action=action)

    with pytest.raises(UnroutableActionError):
        await node(state)
