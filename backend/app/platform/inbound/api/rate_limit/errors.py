"""Rate-limiting error hierarchy (design.md §19, tasks.md task 5.3).

Neither `RateLimitExceededError` nor `LlmBudgetExceededError` fits cleanly
into any of `shared_kernel.errors`'s four subtypes (`NotFoundError`/
`NotAuthorizedError`/`ValidationError`/`ConflictError`) -- design.md §19's
own pseudocode marks a budget-exceeded rejection as its own error taxonomy
category (`error_code: "rate_limited", retryable: False`), distinct from an
authorization failure. Flagged here, not silently forced into the nearest
existing subtype -- `shared_kernel.errors.DomainError` is the base every
module-specific hierarchy ultimately descends from, so subclassing it
directly keeps this catchable alongside every other domain error without
mischaracterizing the cause."""

from app.shared_kernel.errors import DomainError


class RateLimitExceededError(DomainError):
    """A fixed-window or token-bucket rate limit was exceeded (design.md
    §19's auth/token dimension or the chat token-bucket dimension)."""


class LlmBudgetExceededError(RateLimitExceededError):
    """The tenant's `tenants.llm_daily_budget_tokens` daily cap has been
    reached (design.md §19's LLM budget-cap backstop)."""
