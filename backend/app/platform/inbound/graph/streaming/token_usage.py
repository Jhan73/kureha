"""`TokenUsageCallbackHandler` (design.md §19, tasks.md task 12.1's rate-
limiter/budget wiring): aggregates `AIMessage.usage_metadata.total_tokens`
across every LLM call made during ONE graph turn. `/chat` and `/chat/stream`
(`platform/inbound/api/routers/chat.py`) pass one fresh instance per request
via `config={"callbacks": [handler]}` to `graph.ainvoke()`/`graph.astream()`,
then call `LlmBudgetGuard.record_usage(tenant_id=..., tokens_used=handler.
total_tokens)` once the turn completes -- closing the gap PR 12 batch 2's own
`composition_root.py` docstring flagged: "`record_usage(tenant_id,
tokens_used)` has NO caller anywhere in this codebase... meant to run 'al
finalizar el turno' -- a TURN-LEVEL concern `chat.py`'s router owns".

**Defensive `getattr`/`.get`, not a guessed shape.** Whether `ChatAnthropic.
with_structured_output(...).ainvoke()` (every real adapter in this codebase)
surfaces `usage_metadata` transparently through LangChain's own callback
dispatch is UNVERIFIED against a live Anthropic call in this environment
(the same batch-2-flagged uncertainty) -- a call whose `usage_metadata` is
missing/differently-shaped silently contributes `0` to the running total
instead of crashing the turn. `on_llm_end`'s own signature (`response:
LLMResult`, `run_id`, ...) is LangChain's own stable, documented
`AsyncCallbackHandler` contract, confirmed via `inspect.signature` against
the installed package -- not guessed."""

from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult


class TokenUsageCallbackHandler(AsyncCallbackHandler):
    def __init__(self) -> None:
        self.total_tokens = 0

    async def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        for generation_list in response.generations:
            for generation in generation_list:
                message = getattr(generation, "message", None)
                usage = getattr(message, "usage_metadata", None) if message is not None else None
                if usage:
                    self.total_tokens += usage.get("total_tokens", 0) or 0
