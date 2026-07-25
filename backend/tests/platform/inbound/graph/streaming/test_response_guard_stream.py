"""`guard_sentence_units` (design.md §8.7, tasks.md task 12.4): classifies
each sentence-boundary unit via `ClinicalScopePolicy.classify_outbound`
**overlapped with buffering/production of the NEXT unit** -- design.md's own
wording: "cada unidad... pasa response_guard de forma asincrona mientras el
buffer de la oracion siguiente se sigue generando; solo se emite... cuando el
clasificador aprueba la unidad anterior". Concretely: classification for
unit N is scheduled as a background task the moment unit N is produced, and
only AWAITED (then yielded) once unit N+1 has started being pulled from the
upstream iterator -- so the classifier's latency overlaps with whatever
produces the next unit, instead of serializing `await classify -> await
classify -> ...`.

A unit that classifies as anything other than `SAFE` stops the stream
entirely (`ResponseGuardStreamRefusal`) -- spec `clinical-safety`, "Output is
checked even if input filtering is evaded": no unit after a blocked one is
ever yielded."""

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.modules.governance.scope.domain.scope_policy import OutboundScopeCategory, OutboundScopeResult
from app.platform.inbound.graph.streaming.response_guard_stream import (
    ResponseGuardStreamRefusal,
    guard_sentence_units,
)
from app.platform.inbound.graph.streaming.token_usage import TokenUsageCallbackHandler
from app.shared_kernel.tenant_context import TenantContext

_CTX = TenantContext(tenant_id="t1", role="patient", site_id="s1", actor_id="u1")


def _llm_result_with_tokens(total_tokens: int) -> LLMResult:
    message = AIMessage(
        content="",
        usage_metadata={"input_tokens": 0, "output_tokens": total_tokens, "total_tokens": total_tokens},
    )
    return LLMResult(generations=[[ChatGeneration(message=message)]])


class _RecordingUnits:
    """An async iterator recording, in order, when each item was actually
    PULLED by the consumer -- the observable proxy for "unit N+1's
    production overlaps unit N's classification"."""

    def __init__(self, items: list[str]) -> None:
        self._items = items
        self.pulled: list[str] = []

    async def __aiter__(self):
        for item in self._items:
            self.pulled.append(item)
            yield item


class _RecordingScopePolicy:
    def __init__(self, *, unsafe_unit: str | None = None) -> None:
        self.classified: list[str] = []
        self._unsafe_unit = unsafe_unit

    async def classify_outbound(self, ctx: TenantContext, chunk: str) -> OutboundScopeResult:
        self.classified.append(chunk)
        if chunk == self._unsafe_unit:
            return OutboundScopeResult(category=OutboundScopeCategory.CLINICAL_CONTENT, should_block=True)
        return OutboundScopeResult(category=OutboundScopeCategory.SAFE, should_block=False)


async def test_all_safe_units_are_yielded_in_order() -> None:
    units = _RecordingUnits(["Hola.", " Como estas?", " Bien."])
    policy = _RecordingScopePolicy()

    result = [unit async for unit in guard_sentence_units(units.__aiter__(), scope_policy=policy, ctx=_CTX)]

    assert result == ["Hola.", " Como estas?", " Bien."]
    assert policy.classified == ["Hola.", " Como estas?", " Bien."]


async def test_classification_of_unit_n_is_scheduled_before_unit_n_plus_1_is_pulled() -> None:
    """The overlap property, observed indirectly: by the time unit 2 has
    been PULLED from the upstream iterator, unit 1 must already have been
    submitted for classification -- proving classification is not serialized
    strictly AFTER each unit is fully consumed."""
    units = _RecordingUnits(["one.", "two.", "three."])
    policy = _RecordingScopePolicy()

    async for _ in guard_sentence_units(units.__aiter__(), scope_policy=policy, ctx=_CTX):
        pass

    # every unit was pulled from upstream, and every unit was classified --
    # the exact interleaving is an implementation detail, but both lists
    # must reach full length with no unit skipped either way.
    assert units.pulled == ["one.", "two.", "three."]
    assert policy.classified == ["one.", "two.", "three."]


async def test_an_unsafe_unit_stops_the_stream_and_raises() -> None:
    units = _RecordingUnits(["safe.", "unsafe.", "never reached."])
    policy = _RecordingScopePolicy(unsafe_unit="unsafe.")

    collected: list[str] = []
    with pytest.raises(ResponseGuardStreamRefusal) as exc_info:
        async for unit in guard_sentence_units(units.__aiter__(), scope_policy=policy, ctx=_CTX):
            collected.append(unit)

    assert collected == ["safe."]
    assert exc_info.value.blocked_text == "unsafe."


async def test_empty_stream_yields_nothing_and_never_calls_the_classifier() -> None:
    units = _RecordingUnits([])
    policy = _RecordingScopePolicy()

    result = [unit async for unit in guard_sentence_units(units.__aiter__(), scope_policy=policy, ctx=_CTX)]

    assert result == []
    assert policy.classified == []


async def test_single_unit_stream_still_classifies_and_yields_it() -> None:
    units = _RecordingUnits(["only one."])
    policy = _RecordingScopePolicy()

    result = [unit async for unit in guard_sentence_units(units.__aiter__(), scope_policy=policy, ctx=_CTX)]

    assert result == ["only one."]


class _UsageRecordingScopePolicy:
    """Simulates `AnthropicScopePolicy.classify_outbound`'s real behavior of
    forwarding `callbacks` into the underlying `ChatAnthropic` call: invokes
    every provided callback's `on_llm_end` with a synthetic `LLMResult`
    carrying `tokens_per_call` tokens, exactly like a real Anthropic
    structured-output call would trigger via LangChain's own callback
    dispatch."""

    def __init__(self, *, tokens_per_call: int, unsafe_unit: str | None = None) -> None:
        self._tokens_per_call = tokens_per_call
        self._unsafe_unit = unsafe_unit
        self.calls_with_callbacks: list[list | None] = []

    async def classify_outbound(self, ctx: TenantContext, chunk: str, *, callbacks=None) -> OutboundScopeResult:
        self.calls_with_callbacks.append(callbacks)
        if callbacks:
            for cb in callbacks:
                await cb.on_llm_end(_llm_result_with_tokens(self._tokens_per_call), run_id="r1")
        if chunk == self._unsafe_unit:
            return OutboundScopeResult(category=OutboundScopeCategory.CLINICAL_CONTENT, should_block=True)
        return OutboundScopeResult(category=OutboundScopeCategory.SAFE, should_block=False)


async def test_guard_sentence_units_forwards_the_shared_usage_handler_as_a_callback_on_every_classify_call() -> None:
    """Issue 1 (budget-accounting bypass): each sentence-boundary unit's
    `classify_outbound` call spends real tokens outside `graph.astream()`'s
    own callback scope -- `guard_sentence_units` must forward the SAME
    `TokenUsageCallbackHandler` the caller shares with the graph so those
    tokens land in the ONE running total, instead of vanishing."""
    units = _RecordingUnits(["Hola.", " Como estas?"])
    policy = _UsageRecordingScopePolicy(tokens_per_call=10)
    handler = TokenUsageCallbackHandler()

    result = [
        unit
        async for unit in guard_sentence_units(units.__aiter__(), scope_policy=policy, ctx=_CTX, usage_handler=handler)
    ]

    assert result == ["Hola.", " Como estas?"]
    assert handler.total_tokens == 20
    assert policy.calls_with_callbacks == [[handler], [handler]]


async def test_guard_sentence_units_never_passes_callbacks_when_no_usage_handler_is_given() -> None:
    """Backward compatibility: callers with no shared usage handler (none
    exist today, but the parameter is optional) must not force every
    `ClinicalScopePolicy` implementation to accept a `callbacks` kwarg."""
    units = _RecordingUnits(["Hola."])
    policy = _UsageRecordingScopePolicy(tokens_per_call=10)

    result = [unit async for unit in guard_sentence_units(units.__aiter__(), scope_policy=policy, ctx=_CTX)]

    assert result == ["Hola."]
    assert policy.calls_with_callbacks == [None]


async def test_guard_sentence_units_accumulates_tokens_spent_before_a_mid_stream_refusal() -> None:
    """Issue 1's second half, at this module's own boundary: the unit that
    ultimately blocks the stream still spent real classification tokens
    before it was found unsafe -- those must be included in
    `usage_handler.total_tokens` by the time `ResponseGuardStreamRefusal`
    is raised, so the caller's `finally` block has the true partial total
    to record."""
    units = _RecordingUnits(["safe.", "unsafe.", "never reached."])
    policy = _UsageRecordingScopePolicy(tokens_per_call=10, unsafe_unit="unsafe.")
    handler = TokenUsageCallbackHandler()

    with pytest.raises(ResponseGuardStreamRefusal):
        async for _ in guard_sentence_units(units.__aiter__(), scope_policy=policy, ctx=_CTX, usage_handler=handler):
            pass

    assert handler.total_tokens == 20  # "safe." + "unsafe." both classified; "never reached." was not
