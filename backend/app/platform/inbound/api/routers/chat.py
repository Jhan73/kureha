"""Chat router (design.md §8.6, tasks.md task 11.7): `POST /chat` --
non-streaming invocation of `build_graph()` (SSE streaming is task 12.1, a
LATER phase; a plain `await graph.ainvoke(...)` is enough here per this
task's own instructions).

**`thread_id` ownership validation (design.md §8.6) -- the entire point of
this router, not an afterthought.** The request body accepts an OPTIONAL
`client_random_uuid`; if absent, the server generates one
(`design.md: "Si el cliente no envia client_random_uuid, el server genera
uno por request"`). The server then ASSEMBLES the real `thread_id` as
`f"{tenant_id}:{user_id}:{client_random}"` from the AUTHENTICATED actor's
OWN resolved identity (`get_tenant_context`/`get_live_actor`, both populated
by `AccessControlMiddleware` from the caller's own verified access token --
see `access_control/dependencies.py`'s own docstring) -- NEVER from anything
in the request body. An attacker who guesses another session's
`client_random_uuid` still cannot construct that session's real `thread_id`
without ALSO holding that session's own valid access token, since
`tenant_id`/`user_id` come exclusively from server-side token verification,
never from client-supplied input.

**Runs BEHIND `AccessControlMiddleware`, deliberately** -- same posture as
`scheduling.py`/`calendar_oauth.py`: uses the request's already-open,
RLS-scoped `request.state.db_conn` for every business/governance use case
`build_graph()`'s nodes need, and the resolved `TenantContext`/`LiveActor`
to build `RequestContext`. No dedicated RBAC check here -- exactly like
every other router in this package, RBAC is enforced INSIDE the graph
itself (`rbac_gate`), not re-checked at the router boundary.

**`channel` -- `staff_copilot` for any non-`patient` role, `patient_chat`
otherwise.** design.md §8.6 describes both channels sharing this exact
endpoint shape/mechanism ("mismo patron... la unica diferencia es que el
`user_id` en la key es el del staff... y el `RequestContext` incluye `role`
y `site_id` del staff en lugar de `patient_id`") -- `LiveActor.role` is
already resolved by the middleware, so this router derives `channel`
directly from it rather than requiring the client to declare which one it
is (a client-declared channel would be one more value this router would
have to distrust and re-derive anyway).

**Only `request_ctx`/`channel`/`channel_message` are passed as `graph.
ainvoke()`'s input -- a DELIBERATE partial `KurehaState` update, never a
full one.** LangGraph applies every key PRESENT in an `ainvoke` input dict
as an unconditional overwrite of the checkpointed value (same "last write
wins, no reducer" semantics as any node's own return dict) -- a full
`KurehaState` literal with `"proposed_action": None` would WIPE turn N's
pending `proposed_action` before `route_from_start` ever got to read it,
breaking the entire turn-N/turn-N+1 confirmation mechanism design.md §8.9
depends on. `test_build_graph.py`'s own confirmation-round-trip test proves
this partial-dict shape is what actually works against the real compiled
graph.

**`get_graph_dependencies` (tasks.md task 12.3/task 12.2's adapter half, PR
12 batch 1) -- a FastAPI dependency, not a bare function call, deliberately,
the same pattern `get_http_client`/`test_calendar_oauth_router.py`'s
`app.dependency_overrides[get_http_client]` already establishes.** Wires
`GraphDependencies` with the first three real, Anthropic-backed LLM seam
adapters (`scope_policy`/`intent_classifier`/`affirmation_classifier`, one
shared fast-tier `ChatAnthropic`) -- overridable in tests via
`app.dependency_overrides[get_graph_dependencies]` so the test suite never
has to hit a real Anthropic API for THIS router's own wiring tests (see
`tests/platform/inbound/api/routers/test_chat.py`).

**PR 12 batch 2 update: every remaining `GraphDependencies` field is now
also wired to a real adapter.** `scheduling_planner`/`staff_planner` share
ONE reasoner-tier `ChatAnthropic` (design.md §8.10); `reminder_planner`/
`direct_response`/`suggestion_generator` join the existing fast-tier
`ChatAnthropic` this function already builds -- two `ChatAnthropic`
instances total per request (one per tier), not seven. No `GraphDependencies`
field defaults to an `Unwired*` placeholder via this dependency anymore --
see `AnthropicSchedulingPlanner`'s own module docstring for the genuine,
UNRESOLVED "LLM cannot invent a real database id from conversational text"
gap that remains even though every seam is now real.

**PR 12 batch 3 (tasks.md tasks 12.1/12.2/12.4): `POST /chat/stream`.** SSE
equivalent of `chat()` below, sharing the SAME `thread_id`-assembly
(`_assemble_turn`) and rate-limiting (`_enforce_rate_limit`) helpers --
see `_stream_turn`'s own docstring for the SSE event mapping and this
batch's honest, flagged scope boundary on `token` delivery (no adapter in
this codebase streams incremental content today). `_RATE_LIMITED_CHANNELS`
gates the patient-chat token-bucket + LLM-budget cap (design.md §19) to
`patient_chat` only -- both `chat()` and `chat_stream()` now call
`_enforce_rate_limit`/record `TokenUsageCallbackHandler` totals via
`ChatRateLimiter.record_usage()` at turn-end."""

import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from app.composition_root import (
    build_affirmation_classifier,
    build_chat_rate_limiter,
    build_direct_response,
    build_get_tenant,
    build_intent_classifier,
    build_reminder_planner,
    build_runtime_session,
    build_scheduling_planner,
    build_scope_policy,
    build_staff_planner,
    build_suggestion_generator,
    open_checkpointer_connection,
)
from app.platform.inbound.api.access_control.dependencies import get_db_conn, get_live_actor, get_tenant_context
from app.platform.inbound.api.access_control.live_actor import LiveActor
from app.platform.inbound.api.errors import resolve_error
from app.platform.inbound.api.rate_limit.chat_rate_limiter import ChatRateLimiter
from app.platform.inbound.graph.adapters.llm import build_chat_model
from app.platform.inbound.graph.build_graph import GraphDependencies, build_graph
from app.platform.inbound.graph.state import RequestContext
from app.platform.inbound.graph.streaming.response_guard_stream import guard_sentence_units
from app.platform.inbound.graph.streaming.sentence_buffer import SentenceBoundaryBuffer
from app.platform.inbound.graph.streaming.sse import format_sse_event
from app.platform.inbound.graph.streaming.token_usage import TokenUsageCallbackHandler
from app.shared_kernel.tenant_context import TenantContext

router = APIRouter(prefix="/chat", tags=["chat"])

_STAFF_ROLES = frozenset({"reception", "professional", "admin"})

# design.md §19 / spec `platform-hardening` ("Rate Limiting on Patient
# Chat"): the token-bucket + LLM-budget gate applies ONLY to the
# patient-facing channel -- the staff copilot has no equivalent requirement
# named anywhere in design.md/the spec suite, and is presumed trusted
# internal usage (a deliberate, flagged scope boundary, not an oversight).
_RATE_LIMITED_CHANNELS = frozenset({"patient_chat"})


class ChatRequest(BaseModel):
    message: str
    client_random_uuid: str | None = None


class ChatResponse(BaseModel):
    response_text: str | None
    suggestions: list[str] | None
    confirmation: str | None


def _channel_for(role: str) -> str:
    return "staff_copilot" if role in _STAFF_ROLES else "patient_chat"


def _assemble_turn(
    payload: ChatRequest, ctx: TenantContext, live_actor: LiveActor
) -> tuple[str, RequestContext, str]:
    """Shared by `chat()` and `chat_stream()` -- see `chat()`'s own
    docstring for the `thread_id` ownership-assembly contract this
    factors out unchanged (identical for both endpoints, design.md §8.6)."""
    client_random = payload.client_random_uuid or str(uuid.uuid4())
    thread_id = f"{ctx.tenant_id}:{live_actor.user_id}:{client_random}"
    request_ctx = RequestContext(
        tenant_id=ctx.tenant_id,
        role=ctx.role,
        site_id=ctx.site_id,
        user_id=live_actor.user_id,
        patient_id=live_actor.patient_id,
        professional_id=live_actor.professional_id,
    )
    channel = _channel_for(ctx.role)
    return thread_id, request_ctx, channel


async def _enforce_rate_limit(
    *, channel: str, ctx: TenantContext, live_actor: LiveActor, conn: AsyncConnection
) -> ChatRateLimiter | None:
    """Returns the constructed `ChatRateLimiter` (for the caller to also use
    for `record_usage()` at turn-end) when `channel` is rate-limited, `None`
    otherwise -- `None` is a deliberate signal, not an error: the
    staff-copilot channel is simply out of scope for this gate (see this
    module's own `_RATE_LIMITED_CHANNELS` docstring)."""
    if channel not in _RATE_LIMITED_CHANNELS:
        return None
    rate_limiter = build_chat_rate_limiter(conn)
    tenant = await build_get_tenant(conn).execute(ctx.tenant_id)
    await rate_limiter.enforce(
        tenant_id=ctx.tenant_id,
        patient_id=live_actor.patient_id or live_actor.user_id,
        daily_budget_tokens=tenant.llm_daily_budget_tokens,
    )
    return rate_limiter


def get_graph_dependencies() -> GraphDependencies:
    """See this module's own docstring ("`get_graph_dependencies`") for why
    this is a FastAPI dependency rather than a bare call inside `chat()`."""
    fast_llm = build_chat_model("fast")
    reasoner_llm = build_chat_model("reasoner")
    return GraphDependencies(
        intent_classifier=build_intent_classifier(fast_llm),
        affirmation_classifier=build_affirmation_classifier(fast_llm),
        scope_policy=build_scope_policy(fast_llm),
        scheduling_planner=build_scheduling_planner(reasoner_llm),
        staff_planner=build_staff_planner(reasoner_llm),
        reminder_planner=build_reminder_planner(fast_llm),
        direct_response=build_direct_response(fast_llm),
        suggestion_generator=build_suggestion_generator(fast_llm),
    )


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    live_actor: LiveActor = Depends(get_live_actor),
    conn: AsyncConnection = Depends(get_db_conn),
    deps: GraphDependencies = Depends(get_graph_dependencies),
) -> ChatResponse:
    thread_id, request_ctx, channel = _assemble_turn(payload, ctx, live_actor)
    # Raises (`RateLimitExceededError`/`LlmBudgetExceededError`) BEFORE the
    # graph ever runs, for `patient_chat` only -- `errors.py`'s central
    # handler maps both to the §21 `rate-limited` envelope, no special
    # handling needed here (tasks.md task 12.1's rate-limiter/budget
    # wiring, design.md §19).
    rate_limiter = await _enforce_rate_limit(channel=channel, ctx=ctx, live_actor=live_actor, conn=conn)
    usage_handler = TokenUsageCallbackHandler()

    async with open_checkpointer_connection(ctx.tenant_id) as checkpointer_conn:
        checkpointer = AsyncPostgresSaver(checkpointer_conn)
        graph = await build_graph(conn, checkpointer=checkpointer, deps=deps)

        result = await graph.ainvoke(
            {"request_ctx": request_ctx, "channel": channel, "channel_message": payload.message},
            {"configurable": {"thread_id": thread_id}, "callbacks": [usage_handler]},
        )

    if rate_limiter is not None and usage_handler.total_tokens:
        # design.md §19: "al finalizar el turno, el middleware suma los
        # tokens usados" -- best-effort turn-end accounting, never blocks
        # the response (a failed record here would need its own
        # non-blocking posture; see `TokenUsageCallbackHandler`'s own
        # docstring for why `total_tokens` may legitimately be `0`).
        await rate_limiter.record_usage(tenant_id=ctx.tenant_id, tokens_used=usage_handler.total_tokens)

    return ChatResponse(
        response_text=result.get("response_text"),
        suggestions=result.get("suggestions"),
        confirmation=result.get("confirmation"),
    )


async def _units_from_text(text: str) -> AsyncIterator[str]:
    buffer = SentenceBoundaryBuffer()
    for unit in buffer.push(text):
        yield unit
    tail = buffer.flush()
    if tail:
        yield tail


async def _stream_turn(
    payload: ChatRequest,
    ctx: TenantContext,
    live_actor: LiveActor,
    deps: GraphDependencies,
) -> AsyncIterator[str]:
    """The `/chat/stream` SSE body generator (design.md §8.5/§8.7, tasks.md
    tasks 12.1/12.2/12.4).

    **Honest scope boundary, flagged explicitly (not silently oversold):**
    design.md §8.5's `stream_mode=["messages","updates","custom"]` call
    shape is used VERBATIM below, but no LLM adapter in this codebase
    generates incrementally today -- every one of the 8 real Anthropic
    adapters (PR 12 batches 1-2) calls `.with_structured_output(...).
    ainvoke()`, a single-shot call, never `.astream()`. Confirmed
    empirically this batch: LangGraph's `stream_mode="messages"` only
    surfaces genuine token deltas for a chat-model call that itself streams
    internally -- an `.ainvoke()` call yields at most one complete chunk,
    if any. `token` events below are therefore built by taking the graph's
    FINAL `response_text` (observed via the `respond` node's own `updates`
    chunk -- `respond` is the one node every path in `build_graph.py`
    passes through immediately before `END`) and re-segmenting it through
    `SentenceBoundaryBuffer` + `guard_sentence_units` for INCREMENTAL,
    guard-gated delivery -- real value (smaller SSE frames, a genuine
    SECOND independent output-guard pass per spec `clinical-safety`'s
    "Output is checked even if input filtering is evaded"), but not
    concurrent-with-generation the way design.md's prose describes. The
    exact same pipeline starts doing that the moment a future batch swaps
    any adapter's underlying call for a real `.astream()` -- zero changes
    needed here. `status` events (`custom` stream_mode, `streaming/
    status_writer.py`) ARE genuinely live/incremental today -- they fire
    from within `resolve_toolset`/`scheduling_agent`/`staff_agent`/
    `reminders_agent`/`calendar_sync` as the graph actually executes those
    nodes, interleaved chronologically with the `updates` chunks below in
    the SAME `astream()` loop.

    **Every exception, from rate-limiting through a mid-guard refusal
    through an unmapped internal error, becomes an `error` SSE event via
    `resolve_error()` (design.md §21: "toda la superficie... eventos error
    de SSE") -- never an unhandled exception escaping a `StreamingResponse`
    body iterator** (FastAPI's own registered exception handlers cannot
    intercept an exception raised here: response headers/the 200 status
    line are already sent by the time this generator starts yielding).

    **Opens its OWN dedicated `AsyncConnection` (`build_runtime_session().
    begin(live_actor)`) instead of reusing `request.state.db_conn` --
    confirmed empirically, a genuine `StreamingResponse` +
    `AccessControlMiddleware` incompatibility, not a style choice.**
    `AccessControlMiddleware` (a `BaseHTTPMiddleware` subclass) commits and
    CLOSES its request-scoped connection in a `finally` block wrapped
    around `call_next(request)` -- for a normal JSON endpoint this is safe
    (the route function runs to completion, including every DB write,
    BEFORE returning), but Starlette's `BaseHTTPMiddleware` resolves
    `call_next()` as soon as the route function returns its `Response`
    OBJECT, which for a `StreamingResponse` is BEFORE this generator has
    produced a single chunk -- the middleware's `finally` then closes the
    connection while this generator has not even started running yet.
    Reproduced directly against a real Postgres connection this session:
    `sqlalchemy.exc.ResourceClosedError: This Connection is closed` the
    instant `build_graph()` tried to use `request.state.db_conn`. The fix
    mirrors EXACTLY what `AccessControlMiddleware._forward_with_session`
    itself does (`EngineRuntimeSession.begin`/`.end`), just re-run HERE,
    inside the generator, so the connection's lifetime is scoped to the
    STREAM, not to the middleware's `call_next()` return. Committed on a
    clean generator exit, rolled back on any exception (mirrors the
    middleware's own `commit = response.status_code < 500` posture) --
    always closed in a `finally`."""
    thread_id, request_ctx, channel = _assemble_turn(payload, ctx, live_actor)
    rate_limiter: ChatRateLimiter | None = None
    runtime_session = build_runtime_session()
    conn = await runtime_session.begin(live_actor)
    ok = False
    try:
        try:
            rate_limiter = await _enforce_rate_limit(channel=channel, ctx=ctx, live_actor=live_actor, conn=conn)
            usage_handler = TokenUsageCallbackHandler()
            accumulated_state: dict = {}

            async with open_checkpointer_connection(ctx.tenant_id) as checkpointer_conn:
                checkpointer = AsyncPostgresSaver(checkpointer_conn)
                graph = await build_graph(conn, checkpointer=checkpointer, deps=deps)

                config = {"configurable": {"thread_id": thread_id}, "callbacks": [usage_handler]}
                async for stream_mode, chunk in graph.astream(
                    {"request_ctx": request_ctx, "channel": channel, "channel_message": payload.message},
                    config,
                    stream_mode=["messages", "updates", "custom"],
                ):
                    if stream_mode == "custom":
                        yield format_sse_event("status", chunk)
                    elif stream_mode == "updates":
                        for _node_name, partial in chunk.items():
                            accumulated_state.update(partial)
                    # "messages": no adapter streams real content today --
                    # see this function's own docstring. Requested anyway
                    # (design.md's literal call shape) so this loop needs
                    # zero changes once one does.

            final_text = accumulated_state.get("response_text") or ""
            tenant_ctx = request_ctx.to_tenant_context()
            try:
                async for approved_unit in guard_sentence_units(
                    _units_from_text(final_text),
                    scope_policy=deps.scope_policy,
                    ctx=tenant_ctx,
                    usage_handler=usage_handler,
                ):
                    yield format_sse_event("token", {"delta": approved_unit})
            finally:
                # Recorded here, not after the loop -- `guard_sentence_units`
                # itself spends real tokens per sentence-boundary unit
                # (`usage_handler` above is shared with it, see that
                # module's own docstring), so a mid-stream
                # `ResponseGuardStreamRefusal`/any other exception must
                # still report whatever was accumulated up to that point,
                # not silently drop it from the tenant's daily budget.
                if rate_limiter is not None and usage_handler.total_tokens:
                    await rate_limiter.record_usage(tenant_id=ctx.tenant_id, tokens_used=usage_handler.total_tokens)

            yield format_sse_event(
                "done",
                {
                    "audit_ref": accumulated_state.get("audit_ref"),
                    "calendar_sync_status": accumulated_state.get("calendar_sync_status"),
                    "finish_reason": "stop",
                },
            )
            ok = True
        except Exception as exc:  # noqa: BLE001 -- the §21 translation boundary itself, see docstring
            resolved = resolve_error(exc)
            yield format_sse_event("error", resolved.envelope.to_dict())
    finally:
        await runtime_session.end(conn, commit=ok)


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    live_actor: LiveActor = Depends(get_live_actor),
    deps: GraphDependencies = Depends(get_graph_dependencies),
) -> StreamingResponse:
    """`POST /chat/stream` (design.md §8.5, tasks.md task 12.1): SSE
    (`text/event-stream`) equivalent of `POST /chat` above -- same
    auth/`thread_id`-ownership/rate-limiting contract, streamed
    `status`/`token`/`done`/`error` events instead of one JSON body. See
    `_stream_turn`'s own docstring for the exact event-mapping, the
    dedicated-connection fix this endpoint needs (that `POST /chat` does
    NOT), and this batch's honest scope boundary on `token` delivery. Takes
    NO `conn` dependency, deliberately -- see `_stream_turn`'s own
    docstring for why reusing `request.state.db_conn` here is unsafe."""
    return StreamingResponse(_stream_turn(payload, ctx, live_actor, deps), media_type="text/event-stream")
