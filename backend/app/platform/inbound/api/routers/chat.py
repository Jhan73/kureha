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

# Token-bucket + LLM budget apply to patient_chat only (not staff_copilot).
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
    """Shared thread_id / request_ctx / channel assembly for both chat endpoints."""
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
    """Returns the limiter for turn-end `record_usage()`, or None if channel is out of scope."""
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
    """FastAPI dependency so tests can override LLM wiring."""
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
    # patient_chat only; RateLimitExceededError / LlmBudgetExceededError → rate-limited envelope.
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
        # Best-effort turn-end token accounting; never blocks the response.
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
    """SSE body for `/chat/stream`.

    Opens its own DB connection via `build_runtime_session()` — do not reuse
    `request.state.db_conn`: AccessControlMiddleware (BaseHTTPMiddleware) closes
    that connection when the StreamingResponse object is returned, before this
    generator runs.

    Exceptions become an `error` SSE event via `resolve_error()` (headers/200
    already sent; FastAPI exception handlers cannot intercept here).

    Token events are sentence-buffered + guard-gated from final response_text
    (adapters use ainvoke today); status events from stream_mode=custom are live.
    """
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
                # Record even on mid-stream refusal — guard spend must still count.
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
        except Exception as exc:  # noqa: BLE001 -- map to SSE error envelope
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
    """SSE chat; no `conn` dependency — see `_stream_turn` for why."""
    return StreamingResponse(_stream_turn(payload, ctx, live_actor, deps), media_type="text/event-stream")
