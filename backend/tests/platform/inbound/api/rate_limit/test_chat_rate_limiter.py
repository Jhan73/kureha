import pytest

from app.platform.inbound.api.rate_limit.chat_rate_limiter import ChatRateLimiter
from app.platform.inbound.api.rate_limit.errors import LlmBudgetExceededError, RateLimitExceededError


class _FakeTokenBuckets:
    def __init__(self, *, allow: bool) -> None:
        self._allow = allow
        self.calls: list[str] = []

    def try_consume(self, key: str, amount: float = 1.0) -> bool:
        self.calls.append(key)
        return self._allow


class _FakeLlmBudgetGuard:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self._raises = raises
        self.checked: list[tuple[str, int]] = []
        self.recorded: list[tuple[str, int]] = []

    async def check(self, *, tenant_id: str, daily_budget_tokens: int) -> None:
        self.checked.append((tenant_id, daily_budget_tokens))
        if self._raises:
            raise self._raises

    async def record_usage(self, *, tenant_id: str, tokens_used: int) -> int:
        self.recorded.append((tenant_id, tokens_used))
        return tokens_used


async def test_enforce_passes_when_both_gates_allow() -> None:
    buckets = _FakeTokenBuckets(allow=True)
    budget_guard = _FakeLlmBudgetGuard()
    limiter = ChatRateLimiter(buckets, budget_guard)

    await limiter.enforce(tenant_id="t1", patient_id="p1", daily_budget_tokens=1000)

    assert buckets.calls == ["t1:p1"]
    assert budget_guard.checked == [("t1", 1000)]


async def test_enforce_raises_when_the_token_bucket_is_empty_without_checking_budget() -> None:
    buckets = _FakeTokenBuckets(allow=False)
    budget_guard = _FakeLlmBudgetGuard()
    limiter = ChatRateLimiter(buckets, budget_guard)

    with pytest.raises(RateLimitExceededError):
        await limiter.enforce(tenant_id="t1", patient_id="p1", daily_budget_tokens=1000)

    # Cadence gate is cheaper (in-memory, no DB round trip) -- checked first,
    # short-circuiting the budget check when it already denies.
    assert budget_guard.checked == []


async def test_enforce_propagates_llm_budget_exceeded() -> None:
    buckets = _FakeTokenBuckets(allow=True)
    budget_guard = _FakeLlmBudgetGuard(raises=LlmBudgetExceededError("over budget"))
    limiter = ChatRateLimiter(buckets, budget_guard)

    with pytest.raises(LlmBudgetExceededError):
        await limiter.enforce(tenant_id="t1", patient_id="p1", daily_budget_tokens=1000)


async def test_record_usage_delegates_to_the_llm_budget_guard() -> None:
    buckets = _FakeTokenBuckets(allow=True)
    budget_guard = _FakeLlmBudgetGuard()
    limiter = ChatRateLimiter(buckets, budget_guard)

    new_total = await limiter.record_usage(tenant_id="t1", tokens_used=250)

    assert new_total == 250
    assert budget_guard.recorded == [("t1", 250)]
