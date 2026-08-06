from app.shared_kernel.errors import DomainError


class RateLimitExceededError(DomainError):
    """Fixed-window or token-bucket rate limit exceeded."""


class LlmBudgetExceededError(RateLimitExceededError):
    """Tenant daily LLM token budget exceeded."""
