"""tasks.md task 12.2's adapter half: `AnthropicIntentClassifier`, the real
`IntentClassifierPort` adapter `triage` consumes (design.md §8.2/§8.10). No
real network -- same fake-chat-model precedent as
`test_anthropic_scope_policy.py`."""

import pytest

from app.platform.inbound.graph.adapters.anthropic_intent_classifier import AnthropicIntentClassifier
from app.shared_kernel.tenant_context import TenantContext

_ALL_NINE_INTENTS = (
    "schedule",
    "reschedule",
    "cancel",
    "reminder",
    "staff",
    "shift",
    "greeting",
    "capability_query",
    "small_talk",
    "unknown",
)


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


class _Classification:
    def __init__(self, intent: str) -> None:
        self.intent = intent


_CTX = TenantContext(tenant_id="tenant-1", role="patient")


@pytest.mark.parametrize("intent", _ALL_NINE_INTENTS)
async def test_classify_maps_every_one_of_the_nine_intent_categories(intent) -> None:
    llm = _FakeChatModel(_Classification(intent))
    classifier = AnthropicIntentClassifier(llm)

    result = await classifier.classify(_CTX, "un mensaje cualquiera")

    assert result.intent == intent


async def test_classify_sends_the_channel_message_to_the_model() -> None:
    llm = _FakeChatModel(_Classification("schedule"))
    classifier = AnthropicIntentClassifier(llm)

    await classifier.classify(_CTX, "quiero agendar una cita para el martes")

    assert llm.runnable is not None
    sent = llm.runnable.calls[0]
    assert any("quiero agendar una cita para el martes" in str(m.content) for m in sent)


async def test_classify_fails_closed_to_unknown_on_an_llm_error() -> None:
    """An unrouteable/invalid classification must never silently pick a real
    intent it has no basis for -- `unknown` is the ONE category
    `build_graph.py`'s `_route_by_intent` already routes to `escalate_human`
    for, so failing closed here never lets a malformed classification
    silently reach a specialist agent."""
    llm = _FakeChatModel(ValueError("boom"))
    classifier = AnthropicIntentClassifier(llm)

    result = await classifier.classify(_CTX, "cualquier cosa")

    assert result.intent == "unknown"
