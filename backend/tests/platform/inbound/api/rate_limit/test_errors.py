from app.platform.inbound.api.rate_limit.errors import LlmBudgetExceededError, RateLimitExceededError
from app.shared_kernel.errors import DomainError


def test_rate_limit_exceeded_is_a_domain_error() -> None:
    assert issubclass(RateLimitExceededError, DomainError)


def test_llm_budget_exceeded_is_a_rate_limit_exceeded_error() -> None:
    assert issubclass(LlmBudgetExceededError, RateLimitExceededError)


def test_errors_carry_a_message() -> None:
    err = RateLimitExceededError("too many attempts")
    assert str(err) == "too many attempts"
