import asyncio
from collections.abc import AsyncIterator

from app.modules.governance.scope.domain.scope_policy import ClinicalScopePolicy, OutboundScopeCategory
from app.platform.inbound.graph.streaming.token_usage import TokenUsageCallbackHandler
from app.shared_kernel.tenant_context import TenantContext


class ResponseGuardStreamRefusal(Exception):
    """Outbound unit was not SAFE; stop yielding. `blocked_text` is for audit only."""

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
    """Share `usage_handler` with graph.astream so classify_outbound tokens count toward budget."""
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
