"""`TokenUsageCallbackHandler` (design.md §19, tasks.md task 12.1's rate-
limiter/budget wiring): a LangChain `AsyncCallbackHandler` that aggregates
`AIMessage.usage_metadata.total_tokens` across every LLM call made during
ONE graph turn -- passed via `config={"callbacks": [...]}` to `graph.
ainvoke()`/`graph.astream()`, so `LlmBudgetGuard.record_usage()` can be
called with a real total at the end of the turn (design.md §19: "al
finalizar el turno, el middleware suma los tokens usados").

**Defensive by construction, not guessed:** whether `ChatAnthropic.with_
structured_output(...).ainvoke()` (every real LLM adapter in this codebase)
surfaces `usage_metadata` transparently through LangChain's callback
machinery is UNVERIFIED against a live API in this environment (PR 12 batch
2's own flagged gap) -- `on_llm_end` here defensively `getattr`s every field
so a shape mismatch yields `0` for that call instead of crashing the whole
turn; the aggregation logic itself is proven directly against a synthetic
`LLMResult`, LangChain's own stable, documented callback shape."""

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.platform.inbound.graph.streaming.token_usage import TokenUsageCallbackHandler


def _llm_result(*, total_tokens: int) -> LLMResult:
    message = AIMessage(
        content="hola",
        usage_metadata={"input_tokens": total_tokens - 5, "output_tokens": 5, "total_tokens": total_tokens},
    )
    return LLMResult(generations=[[ChatGeneration(message=message)]])


async def test_on_llm_end_accumulates_total_tokens_from_usage_metadata() -> None:
    handler = TokenUsageCallbackHandler()

    await handler.on_llm_end(_llm_result(total_tokens=150), run_id="r1")

    assert handler.total_tokens == 150


async def test_on_llm_end_accumulates_across_multiple_calls() -> None:
    handler = TokenUsageCallbackHandler()

    await handler.on_llm_end(_llm_result(total_tokens=100), run_id="r1")
    await handler.on_llm_end(_llm_result(total_tokens=50), run_id="r2")

    assert handler.total_tokens == 150


async def test_on_llm_end_tolerates_a_message_with_no_usage_metadata() -> None:
    handler = TokenUsageCallbackHandler()
    message = AIMessage(content="hola")  # no usage_metadata at all
    result = LLMResult(generations=[[ChatGeneration(message=message)]])

    await handler.on_llm_end(result, run_id="r1")

    assert handler.total_tokens == 0


async def test_on_llm_end_handles_multiple_generations_in_one_result() -> None:
    handler = TokenUsageCallbackHandler()
    result = LLMResult(
        generations=[
            [
                ChatGeneration(
                    message=AIMessage(content="a", usage_metadata={"input_tokens": 5, "output_tokens": 5, "total_tokens": 10})
                )
            ],
            [
                ChatGeneration(
                    message=AIMessage(content="b", usage_metadata={"input_tokens": 5, "output_tokens": 5, "total_tokens": 10})
                )
            ],
        ]
    )

    await handler.on_llm_end(result, run_id="r1")

    assert handler.total_tokens == 20


async def test_total_tokens_starts_at_zero() -> None:
    handler = TokenUsageCallbackHandler()

    assert handler.total_tokens == 0
