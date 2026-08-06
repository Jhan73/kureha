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
    """Routes to `direct_respond` via greeting intent (skips scope/consent/RBAC gates)."""

    async def classify(self, ctx, message: str) -> IntentClassificationResult:
        return IntentClassificationResult(intent="greeting")


class _FakeDirectResponse:
    async def respond(self, ctx, *, intent, message, allowed_actions) -> DirectResponsePlan:
        return DirectResponsePlan(text="¡Hola! Soy Tony, tu asistente para gestionar citas.")


class _FakeSafeScopePolicy:
    """No-op outbound scope policy so chat router tests stay network-free."""

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
    actor = seed_reception_actor(email="chat-reception-real-llm@example.com")
    token = mint_access_token(
        tenant_id=actor["tenant_id"], site_id=actor["site_id"], role="reception", user_id=actor["user_id"]
    )

    response = client.post("/chat", json={"message": "hola"}, headers=auth_headers(token))

    assert response.status_code == 200
    body = response.json()
    assert body["response_text"]


def _parse_sse_events(raw: str) -> list[tuple[str, dict]]:
    """Split a raw SSE body into `(event, data)` pairs for one-shot asserts."""
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


def _llm_result_with_tokens(total_tokens: int) -> LLMResult:
    message = AIMessage(
        content="",
        usage_metadata={"input_tokens": 0, "output_tokens": total_tokens, "total_tokens": total_tokens},
    )
    return LLMResult(generations=[[ChatGeneration(message=message)]])


class _FakeTwoSentenceDirectResponse:
    """Two sentence-boundary units so the outbound guard classifies twice."""

    async def respond(self, ctx, *, intent, message, allowed_actions) -> DirectResponsePlan:
        return DirectResponsePlan(text="Hola. Como estas?")


class _PartiallyUnsafeScopePolicyWithUsage:
    """Records token usage per classify call, then blocks the second unit."""

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
    """Captures `record_usage()` calls without hitting the real budget store."""

    def __init__(self) -> None:
        self.recorded: list[tuple[str, int]] = []

    async def enforce(self, *, tenant_id: str, patient_id: str, daily_budget_tokens: int) -> None:
        return None

    async def record_usage(self, *, tenant_id: str, tokens_used: int) -> int:
        self.recorded.append((tenant_id, tokens_used))
        return tokens_used


class _FakeBoomIntentClassifier:
    """Raises an unmapped error whose message must not reach the SSE client."""

    async def classify(self, ctx, message: str) -> IntentClassificationResult:
        raise RuntimeError("db connection string leaked: postgres://user:pass@host/db")


def test_chat_stream_surfaces_an_unmapped_exception_as_a_non_leaky_internal_error_event(client) -> None:
    app.dependency_overrides[get_graph_dependencies] = lambda: GraphDependencies(
        intent_classifier=_FakeBoomIntentClassifier(),
    )
    try:
        actor = seed_reception_actor(email="chat-stream-unmapped-boom@example.com")
        token = mint_access_token(
            tenant_id=actor["tenant_id"], site_id=actor["site_id"], role="reception", user_id=actor["user_id"]
        )

        with client.stream(
            "POST", "/chat/stream", json={"message": "hola"}, headers=auth_headers(token)
        ) as response:
            assert response.status_code == 200
            raw = response.read().decode("utf-8")

        events = _parse_sse_events(raw)
        assert events[-1][0] == "error"
        envelope = events[-1][1]
        assert envelope["error_code"] == "internal_error"
        assert envelope["category"] == "internal"
        assert envelope["retryable"] is False
        assert "postgres://" not in envelope["user_message"]
        assert "RuntimeError" not in envelope["user_message"]
    finally:
        app.dependency_overrides.pop(get_graph_dependencies, None)


def test_chat_stream_records_partial_token_usage_even_when_the_guard_refuses_mid_stream(client) -> None:
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
