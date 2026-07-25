"""Task 11.7 / PR 12 batch 1+2 (tasks.md task 12.2's adapter half/12.3/
12.5/12.6/12.7): chat router (`POST /chat`) -- real `thread_id` ownership
assembly (server-side, from the authenticated actor's own token claims),
checkpointer connection wiring, non-streaming graph invocation, and (batch
1) real Anthropic-backed wiring for `intent_classifier`/
`affirmation_classifier`/`scope_policy`, (batch 2) the remaining five seams
(`scheduling_planner`/`staff_planner`/`reminder_planner`/`direct_response`/
`suggestion_generator`) via `get_graph_dependencies`.

**Batch 2 update: `get_graph_dependencies`' default no longer has ANY
`Unwired*`-backed field** -- the OLD version of this test proved wiring by
observing an `UnwiredDirectResponse`'s `NotImplementedError` surface through
`register_exception_handlers`; that premise no longer holds (`direct_
response` is real by default too now). The replacement test below overrides
EVERY seam `direct_respond`'s path touches (`intent_classifier`/
`direct_response`/`scope_policy`) with fakes and asserts a genuine
SUCCESSFUL end-to-end turn instead -- still no network call, still proving
the endpoint's auth/thread_id/checkpointer/graph-construction wiring is
genuinely reached and exercised end-to-end, just via a different observable
(a 200 with real response content) now that there is no Unwired seam left to
surface as a proxy for "the wiring was reached"."""

import json

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

import app.platform.inbound.api.routers.chat as chat_module
from app.config import settings
from app.main import app
from app.modules.governance.scope.domain.scope_policy import (
    InboundScopeCategory,
    InboundScopeResult,
    OutboundScopeCategory,
    OutboundScopeResult,
)
from app.platform.inbound.api.routers.chat import get_graph_dependencies
from app.platform.inbound.graph.build_graph import GraphDependencies
from app.platform.inbound.graph.ports.direct_response import DirectResponsePlan
from app.platform.inbound.graph.ports.intent_classifier import IntentClassificationResult
from tests.platform.inbound.api.routers.conftest import (
    auth_headers,
    mint_access_token,
    seed_patient_actor,
    seed_reception_actor,
)


class _FakeGreetingIntentClassifier:
    """Classifies everything as `greeting` -- a "light" intent
    (`build_graph.py`'s `_route_from_triage`) that routes straight to
    `direct_respond`, bypassing `clinical_scope_validator`/`consent_gate`/
    `rbac_gate` entirely, so `affirmation_classifier` never needs to be
    exercised for this test's purpose either."""

    async def classify(self, ctx, message: str) -> IntentClassificationResult:
        return IntentClassificationResult(intent="greeting")


class _FakeDirectResponse:
    async def respond(self, ctx, *, intent, message, allowed_actions) -> DirectResponsePlan:
        return DirectResponsePlan(text="¡Hola! Soy Tony, tu asistente para gestionar citas.")


class _FakeSafeScopePolicy:
    """`direct_respond -> response_guard` (unconditional edge,
    `build_graph.py`) still calls `deps.scope_policy.classify_outbound` on
    the real text `_FakeDirectResponse` above produces -- overridden here so
    this stays a network-free unit test (the default `scope_policy` is a
    REAL `AnthropicScopePolicy` since PR 12 batch 1)."""

    async def classify_inbound(self, ctx, message: str) -> InboundScopeResult:
        return InboundScopeResult(category=InboundScopeCategory.IN_SCOPE, should_escalate=False)

    async def classify_outbound(self, ctx, chunk: str, *, callbacks=None) -> OutboundScopeResult:
        # `callbacks` accepted (and ignored) for parity with the real
        # `AnthropicScopePolicy`: `/chat/stream` always shares its
        # `usage_handler` with `guard_sentence_units`, which forwards it as
        # `callbacks` on every `classify_outbound` call (issue 1 fix).
        return OutboundScopeResult(category=OutboundScopeCategory.SAFE, should_block=False)


def test_chat_requires_authentication(client) -> None:
    response = client.post("/chat", json={"message": "hola"})

    assert response.status_code == 401


def test_chat_reaches_the_graph_and_completes_a_full_turn_end_to_end(client) -> None:
    """`get_graph_dependencies` wires every seam to a REAL, Anthropic-backed
    adapter by default (batch 1+2) -- overridden here (same `app.
    dependency_overrides[...]` pattern `test_calendar_oauth_router.py`'s
    `get_http_client` override establishes) with fakes for the THREE seams
    a `greeting` turn actually touches (`intent_classifier`/
    `direct_response`/`scope_policy`) so this test never needs a real
    Anthropic call, while still proving the endpoint's own wiring end to
    end: auth -> thread_id assembly -> checkpointer connection ->
    `build_graph()` -> a REAL, successful `graph.ainvoke()` -> a genuine
    `response_text` returned to the client."""
    app.dependency_overrides[get_graph_dependencies] = lambda: GraphDependencies(
        intent_classifier=_FakeGreetingIntentClassifier(),
        direct_response=_FakeDirectResponse(),
        scope_policy=_FakeSafeScopePolicy(),
    )
    try:
        actor = seed_reception_actor(email="chat-reception@example.com")
        token = mint_access_token(
            tenant_id=actor["tenant_id"], site_id=actor["site_id"], role="reception", user_id=actor["user_id"]
        )

        response = client.post("/chat", json={"message": "hola"}, headers=auth_headers(token))

        assert response.status_code == 200
        body = response.json()
        assert body["response_text"] == "¡Hola! Soy Tony, tu asistente para gestionar citas."
    finally:
        app.dependency_overrides.pop(get_graph_dependencies, None)


@pytest.mark.skipif(not settings.anthropic_api_key, reason="requires ANTHROPIC_API_KEY for a real Anthropic call")
def test_chat_with_a_real_anthropic_key_reaches_a_real_end_to_end_turn(client) -> None:
    """Genuine integration smoke test -- NOT part of the default `uv run
    pytest` run (no network calls in the default suite, matching this
    codebase's existing convention, e.g. `test_calendar_oauth_router.py`'s
    `skipif(not settings.aws_endpoint_url, ...)`). With no dependency
    override, `get_graph_dependencies`' default (every seam real, batch 1+2)
    actually classifies "hola", generates a real Tony greeting, and passes
    the real output-scope guard -- asserting a genuine 200 with non-empty
    `response_text`, proving the end-to-end wiring against the live API."""
    actor = seed_reception_actor(email="chat-reception-real-llm@example.com")
    token = mint_access_token(
        tenant_id=actor["tenant_id"], site_id=actor["site_id"], role="reception", user_id=actor["user_id"]
    )

    response = client.post("/chat", json={"message": "hola"}, headers=auth_headers(token))

    assert response.status_code == 200
    body = response.json()
    assert body["response_text"]


# ---------------------------------------------------------------------------
# PR 12 batch 3 (tasks.md tasks 12.1/12.2/12.4): `POST /chat/stream` -- SSE
# `status`/`token`/`done`/`error` events, sentence-boundary buffering +
# streaming `response_guard`, and the patient-chat rate limiter/budget
# wiring (design.md §8.5/§8.7/§19).
# ---------------------------------------------------------------------------


def _parse_sse_events(raw: str) -> list[tuple[str, dict]]:
    """Splits a raw SSE body (`event: ...\\ndata: ...\\n\\n` frames,
    `streaming/sse.py`'s own `format_sse_event` shape) into `(event, data)`
    pairs -- the same parsing job a real `fetch`+`ReadableStream` client
    (design.md §8.5) does incrementally, done here in one shot against the
    full response body `TestClient` already buffered."""
    events: list[tuple[str, dict]] = []
    for frame in raw.strip("\n").split("\n\n"):
        if not frame.strip():
            continue
        lines = frame.split("\n")
        event = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        events.append((event, data))
    return events


def test_chat_stream_requires_authentication(client) -> None:
    response = client.post("/chat/stream", json={"message": "hola"})

    assert response.status_code == 401


def test_chat_stream_streams_token_and_done_events_for_a_greeting_turn(client) -> None:
    """Same fakes as the non-streaming `/chat` end-to-end test above -- a
    `greeting` turn never reaches any of the 5 status-instrumented nodes
    (`resolve_toolset`/`scheduling_agent`/`staff_agent`/`reminders_agent`/
    `calendar_sync`, all downstream of `clinical_scope_validator`/
    `consent_gate`, which `direct_respond`'s fast lane bypasses entirely per
    `build_graph.py`'s own `_route_from_triage`) -- so no `status` event is
    expected here; asserting `token`+`done` proves the SSE transport,
    checkpointer wiring, and sentence-boundary + streaming-guard pipeline
    end to end instead. A dedicated `status`-event scenario is covered at
    the unit level by each instrumented node's own test (e.g. `tests/
    platform/inbound/graph/nodes/test_scheduling_agent.py`), not re-proven
    here against a real graph run (would need real consent/RBAC seeding
    for a `schedule` intent with no additional wiring value beyond what
    those unit tests already prove)."""
    app.dependency_overrides[get_graph_dependencies] = lambda: GraphDependencies(
        intent_classifier=_FakeGreetingIntentClassifier(),
        direct_response=_FakeDirectResponse(),
        scope_policy=_FakeSafeScopePolicy(),
    )
    try:
        actor = seed_reception_actor(email="chat-stream-reception@example.com")
        token = mint_access_token(
            tenant_id=actor["tenant_id"], site_id=actor["site_id"], role="reception", user_id=actor["user_id"]
        )

        with client.stream(
            "POST", "/chat/stream", json={"message": "hola"}, headers=auth_headers(token)
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            raw = response.read().decode("utf-8")

        events = _parse_sse_events(raw)
        event_types = [event for event, _ in events]

        assert "token" in event_types
        assert event_types[-1] == "done"
        token_text = "".join(data["delta"] for event, data in events if event == "token")
        assert token_text == "¡Hola! Soy Tony, tu asistente para gestionar citas."
        done_data = next(data for event, data in events if event == "done")
        assert done_data["finish_reason"] == "stop"
    finally:
        app.dependency_overrides.pop(get_graph_dependencies, None)


def test_chat_enforces_the_rate_limiter_for_patient_chat_after_the_burst_capacity(client) -> None:
    """design.md §19 layer 3 / spec `platform-hardening`'s "Rate Limiting on
    Patient Chat": the token-bucket cadence gate applies ONLY to
    `patient_chat` (`_channel_for`'s own derivation) -- the reception-actor
    tests above never touch it. `chat_rate_limit_capacity` (default 5)
    messages succeed; the next one is denied with the SAME §21 envelope
    every other rate-limited surface uses.

    **`refill_per_second=0` for this test, deliberately.** `_chat_token_
    buckets` is a real, process-wide singleton (design.md §19: the whole
    point of a token bucket is to persist across requests) built from
    `settings.chat_rate_limit_refill_per_second` -- confirmed empirically
    THIS session that the REAL configured refill rate (0.5/s) partially
    replenishes the bucket during this test's own real per-request latency
    (~0.6-0.8s per full graph round trip through `TestClient`, ~0.3-0.4
    tokens refilled between consumes), making "exactly `capacity+1`
    requests" a flaky assumption -- patched to a zero-refill registry here
    for a deterministic assertion, restored in `finally`."""
    import app.composition_root as composition_root_module
    from app.platform.inbound.api.rate_limit.token_bucket import TokenBucketRegistry
    from app.shared_kernel.clock import SystemClock

    original_registry = composition_root_module._chat_token_buckets
    composition_root_module._chat_token_buckets = TokenBucketRegistry(
        capacity=settings.chat_rate_limit_capacity, refill_per_second=0.0, clock=SystemClock()
    )
    app.dependency_overrides[get_graph_dependencies] = lambda: GraphDependencies(
        intent_classifier=_FakeGreetingIntentClassifier(),
        direct_response=_FakeDirectResponse(),
        scope_policy=_FakeSafeScopePolicy(),
    )
    try:
        actor = seed_patient_actor()
        token = mint_access_token(
            tenant_id=actor["tenant_id"], site_id=actor["site_id"], role="patient", user_id=actor["user_id"]
        )

        responses = [
            client.post("/chat", json={"message": "hola"}, headers=auth_headers(token))
            for _ in range(settings.chat_rate_limit_capacity + 1)
        ]

        assert all(r.status_code == 200 for r in responses[:-1])
        last = responses[-1]
        assert last.status_code == 429
        body = last.json()
        assert body["error_code"] == "rate_limited"
        assert body["category"] == "rate-limited"
    finally:
        app.dependency_overrides.pop(get_graph_dependencies, None)
        composition_root_module._chat_token_buckets = original_registry


# ---------------------------------------------------------------------------
# Post-review fix (fresh-context adversarial review of PR 12 batch 3, not
# tasks.md scope): `guard_sentence_units`' classification calls spend real
# tokens outside `graph.astream()`'s own `usage_handler` scope, and
# `record_usage()` used to run only AFTER that guard loop completed --
# losing every token spent so far when `ResponseGuardStreamRefusal` (or any
# other exception) cut the loop short. Both proven together here, against
# the real router.
# ---------------------------------------------------------------------------


def _llm_result_with_tokens(total_tokens: int) -> LLMResult:
    message = AIMessage(
        content="",
        usage_metadata={"input_tokens": 0, "output_tokens": total_tokens, "total_tokens": total_tokens},
    )
    return LLMResult(generations=[[ChatGeneration(message=message)]])


class _FakeTwoSentenceDirectResponse:
    """Produces text with two sentence-boundary units so `guard_sentence_
    units` schedules more than one classification call -- the second one
    (`" Como estas?"`) is the one `_PartiallyUnsafeScopePolicyWithUsage`
    below blocks."""

    async def respond(self, ctx, *, intent, message, allowed_actions) -> DirectResponsePlan:
        return DirectResponsePlan(text="Hola. Como estas?")


class _PartiallyUnsafeScopePolicyWithUsage:
    """`classify_outbound` invokes every forwarded callback's `on_llm_end`
    with a fixed token count (mirroring `AnthropicScopePolicy`'s real
    callback forwarding, proven separately in `test_anthropic_scope_
    policy.py`), then blocks the SECOND sentence-boundary unit -- so the
    stream fails mid-guard, after having already spent classification
    tokens on both the first (approved) and second (blocking) unit."""

    def __init__(self, *, tokens_per_call: int, unsafe_unit: str) -> None:
        self._tokens_per_call = tokens_per_call
        self._unsafe_unit = unsafe_unit

    async def classify_inbound(self, ctx, message: str) -> InboundScopeResult:
        return InboundScopeResult(category=InboundScopeCategory.IN_SCOPE, should_escalate=False)

    async def classify_outbound(self, ctx, chunk: str, *, callbacks=None) -> OutboundScopeResult:
        if callbacks:
            for cb in callbacks:
                await cb.on_llm_end(_llm_result_with_tokens(self._tokens_per_call), run_id="r1")
        if chunk == self._unsafe_unit:
            return OutboundScopeResult(category=OutboundScopeCategory.CLINICAL_CONTENT, should_block=True)
        return OutboundScopeResult(category=OutboundScopeCategory.SAFE, should_block=False)


class _FakeRateLimiterRecordingUsage:
    """Stands in for `ChatRateLimiter` (`build_chat_rate_limiter`'s real
    return value) so this test can assert on `record_usage()` calls
    directly, without depending on the daily-budget counter's own separate,
    always-elevated-connection commit semantics (`composition_root.py`'s
    `_ElevatedRateCounterStore`) to observe the fix."""

    def __init__(self) -> None:
        self.recorded: list[tuple[str, int]] = []

    async def enforce(self, *, tenant_id: str, patient_id: str, daily_budget_tokens: int) -> None:
        return None

    async def record_usage(self, *, tenant_id: str, tokens_used: int) -> int:
        self.recorded.append((tenant_id, tokens_used))
        return tokens_used


def test_chat_stream_records_partial_token_usage_even_when_the_guard_refuses_mid_stream(client) -> None:
    """Issue 1, proven end to end: a `ResponseGuardStreamRefusal` raised
    mid-guard must still reach `rate_limiter.record_usage()` with whatever
    `usage_handler.total_tokens` had accumulated up to that point (BOTH
    sentence units' classification spend, since the second one is only
    discovered unsafe AFTER its own classification call already ran) --
    never silently dropped from the tenant's daily LLM budget."""
    fake_limiter = _FakeRateLimiterRecordingUsage()
    original_builder = chat_module.build_chat_rate_limiter
    chat_module.build_chat_rate_limiter = lambda conn: fake_limiter

    app.dependency_overrides[get_graph_dependencies] = lambda: GraphDependencies(
        intent_classifier=_FakeGreetingIntentClassifier(),
        direct_response=_FakeTwoSentenceDirectResponse(),
        scope_policy=_PartiallyUnsafeScopePolicyWithUsage(tokens_per_call=42, unsafe_unit=" Como estas?"),
    )
    try:
        actor = seed_patient_actor()
        token = mint_access_token(
            tenant_id=actor["tenant_id"], site_id=actor["site_id"], role="patient", user_id=actor["user_id"]
        )

        with client.stream(
            "POST", "/chat/stream", json={"message": "hola"}, headers=auth_headers(token)
        ) as response:
            assert response.status_code == 200
            raw = response.read().decode("utf-8")

        events = _parse_sse_events(raw)
        assert events[-1][0] == "error"
        assert events[-1][1]["category"] == "clinical-scope-refused"

        assert fake_limiter.recorded == [(actor["tenant_id"], 84)]
    finally:
        app.dependency_overrides.pop(get_graph_dependencies, None)
        chat_module.build_chat_rate_limiter = original_builder
