import pytest

from app.platform.inbound.graph.adapters.anthropic_affirmation_classifier import AnthropicAffirmationClassifier
from app.shared_kernel.tenant_context import TenantContext


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


class _Classification:
    def __init__(self, decision: str) -> None:
        self.decision = decision


_CTX = TenantContext(tenant_id="tenant-1", role="patient")


@pytest.mark.parametrize("decision", ["affirmed", "declined", "unclear"])
async def test_classify_maps_all_three_verdicts(decision) -> None:
    llm = _FakeChatModel(_Classification(decision))
    classifier = AnthropicAffirmationClassifier(llm)

    result = await classifier.classify(_CTX, "si, dale", pending_action_summary="Reservo una cita el martes 10:00.")

    assert result.decision == decision


async def test_classify_sends_both_the_message_and_the_pending_action_summary() -> None:
    llm = _FakeChatModel(_Classification("affirmed"))
    classifier = AnthropicAffirmationClassifier(llm)

    await classifier.classify(_CTX, "dale", pending_action_summary="Reservo una cita con la Dra. X el martes 10:00.")

    assert llm.runnable is not None
    sent = llm.runnable.calls[0]
    joined = " ".join(str(m.content) for m in sent)
    assert "dale" in joined
    assert "Reservo una cita con la Dra. X el martes 10:00." in joined


async def test_classify_fails_closed_to_unclear_on_an_llm_error() -> None:
    llm = _FakeChatModel(RuntimeError("boom"))
    classifier = AnthropicAffirmationClassifier(llm)

    result = await classifier.classify(_CTX, "algo", pending_action_summary="Reservo una cita.")

    assert result.decision == "unclear"
