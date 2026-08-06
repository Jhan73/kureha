from typing import Protocol

from app.platform.inbound.api.rate_limit.errors import RateLimitExceededError


class _TokenBucketsPort(Protocol):
    def try_consume(self, key: str, amount: float = 1.0) -> bool: ...


class _LlmBudgetGuardPort(Protocol):
    async def check(self, *, tenant_id: str, daily_budget_tokens: int) -> None: ...
    async def record_usage(self, *, tenant_id: str, tokens_used: int) -> int: ...


class ChatRateLimiter:
    def __init__(self, token_buckets: _TokenBucketsPort, llm_budget_guard: _LlmBudgetGuardPort) -> None:
        self._token_buckets = token_buckets
        self._llm_budget_guard = llm_budget_guard

    async def enforce(self, *, tenant_id: str, patient_id: str, daily_budget_tokens: int) -> None:
        key = f"{tenant_id}:{patient_id}"
        if not self._token_buckets.try_consume(key):
            raise RateLimitExceededError(f"chat cadence rate limit exceeded for {key}")

        await self._llm_budget_guard.check(tenant_id=tenant_id, daily_budget_tokens=daily_budget_tokens)

    async def record_usage(self, *, tenant_id: str, tokens_used: int) -> int:
        """Turn-end token accounting counterpart to `enforce`."""
        return await self._llm_budget_guard.record_usage(tenant_id=tenant_id, tokens_used=tokens_used)
