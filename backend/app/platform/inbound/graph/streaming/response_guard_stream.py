"""`guard_sentence_units` (design.md §8.7, tasks.md task 12.4): the
STREAMING-specific extension of `response_guard` -- classifies each
sentence-boundary unit (`SentenceBoundaryBuffer`) via `ClinicalScopePolicy.
classify_outbound`, **overlapped with the production of the next unit**, so
only an already-approved unit is ever handed to the SSE `token` emitter.

**NOT redundant with `nodes/response_guard.py` (task 11.5) on the
operational-success path -- the opposite is true.** `build_graph.py`'s own
edges run `response_guard` BEFORE `respond` on every path, including
`persist_and_audit`/`calendar_sync -> response_guard -> respond`; `respond`
is the node that COMPOSES `state["response_text"]` from `outcome`/
`proposed_action.summary` on that path, so the graph's own guard classifies
`state.get("response_text") or ""` -- an EMPTY string -- on exactly that
path (see `response_guard.py`'s and `respond.py`'s own docstrings for the
full reasoning). THIS module runs downstream of `respond`, in `/chat/
stream`'s own generator (`chat.py`'s `_stream_turn`), against the REAL
final composed text -- making it the ONLY output-scope guard that actually
inspects that text on the `/chat/stream` path. Every OTHER path
(`direct_respond`, `confirmation_gate`'s `needed`/decline branches) already
sets `response_text` to real content before the graph's own
`response_guard` runs, so on those paths this module's classification is a
genuine second pass over the same text -- true redundancy only there, never
on the operational-success path.

TODO: `/chat` (non-streaming) has no equivalent second guard pass, so an
operational-success turn's real composed text never reaches ANY
output-scope classifier on that endpoint -- a pre-existing gap from task
11.5, not addressed here.

**Concurrency mechanism, precisely:** classification for unit N is
scheduled as an `asyncio.Task` the instant unit N is available, then the
loop proceeds to PULL unit N+1 from the upstream iterator (which is where
"waiting for the next unit to be produced" happens) before ever awaiting
unit N's task -- so the classifier's own latency overlaps with whatever the
upstream iterator does to produce the next item, rather than a strictly
serialized `await classify(); await classify(); ...` chain."""

import asyncio
from collections.abc import AsyncIterator

from app.modules.governance.scope.domain.scope_policy import ClinicalScopePolicy, OutboundScopeCategory
from app.platform.inbound.graph.streaming.token_usage import TokenUsageCallbackHandler
from app.shared_kernel.tenant_context import TenantContext


class ResponseGuardStreamRefusal(Exception):
    """Raised when a sentence-boundary unit classifies as anything other
    than `SAFE` mid-stream -- spec `clinical-safety`, "Output is checked
    even if input filtering is evaded": no unit produced AFTER the blocked
    one is ever yielded. `blocked_text` carries the unit that failed, for
    the caller (`/chat/stream`) to log/audit -- never re-sent to the client
    (the SSE `error` event uses the same non-leaky §21 envelope every other
    error surface uses, not this raw text)."""

    def __init__(self, blocked_text: str) -> None:
        super().__init__("response_guard blocked a streamed unit")
        self.blocked_text = blocked_text


async def guard_sentence_units(
    units: AsyncIterator[str],
    *,
    scope_policy: ClinicalScopePolicy,
    ctx: TenantContext,
    usage_handler: TokenUsageCallbackHandler | None = None,
) -> AsyncIterator[str]:
    """`usage_handler`, when given, is the SAME `TokenUsageCallbackHandler`
    instance the caller already passed to `graph.astream()`'s own
    `config={"callbacks": [...]}` -- each `classify_outbound` call is a real
    `ChatAnthropic` invocation (`AnthropicScopePolicy`) that spends real
    tokens outside the graph's own callback scope; forwarding the SAME
    handler here (rather than a second, separate counter) is what lets
    those tokens land in the ONE running total `chat.py` later reports to
    `ChatRateLimiter.record_usage()` -- otherwise every `/chat/stream` turn
    silently undercounts spend against `tenants.llm_daily_budget_tokens`
    proportionally to how many sentences the response has."""
    pending_task: asyncio.Task | None = None
    pending_text: str | None = None

    def _classify(unit: str) -> asyncio.Task:
        if usage_handler is not None:
            return asyncio.create_task(scope_policy.classify_outbound(ctx, unit, callbacks=[usage_handler]))
        return asyncio.create_task(scope_policy.classify_outbound(ctx, unit))

    async for unit in units:
        if pending_task is not None:
            result = await pending_task
            if result.category is not OutboundScopeCategory.SAFE:
                raise ResponseGuardStreamRefusal(pending_text)
            yield pending_text
        pending_text = unit
        pending_task = _classify(unit)

    if pending_task is not None:
        result = await pending_task
        if result.category is not OutboundScopeCategory.SAFE:
            raise ResponseGuardStreamRefusal(pending_text)
        yield pending_text
