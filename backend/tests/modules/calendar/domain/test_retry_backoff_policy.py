from datetime import datetime, timedelta, timezone

from app.modules.calendar.domain.retry_backoff_policy import RetryBackoffPolicy

_T0 = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def test_not_due_before_the_backoff_window_elapses() -> None:
    policy = RetryBackoffPolicy(base_seconds=60, max_attempts=5)

    due = policy.is_due(attempts=0, updated_at=_T0, now=_T0 + timedelta(seconds=30))

    assert due is False


def test_due_once_the_backoff_window_elapses() -> None:
    policy = RetryBackoffPolicy(base_seconds=60, max_attempts=5)

    due = policy.is_due(attempts=0, updated_at=_T0, now=_T0 + timedelta(seconds=61))

    assert due is True


def test_backoff_window_grows_exponentially_with_attempts() -> None:
    policy = RetryBackoffPolicy(base_seconds=60, max_attempts=5)

    # attempts=2 -> backoff = 60 * 2**2 = 240s; 120s elapsed is not enough yet.
    not_yet = policy.is_due(attempts=2, updated_at=_T0, now=_T0 + timedelta(seconds=120))
    now_due = policy.is_due(attempts=2, updated_at=_T0, now=_T0 + timedelta(seconds=241))

    assert not_yet is False
    assert now_due is True


def test_never_due_once_attempts_reaches_the_cap() -> None:
    policy = RetryBackoffPolicy(base_seconds=60, max_attempts=3)

    due = policy.is_due(attempts=3, updated_at=_T0, now=_T0 + timedelta(days=365))

    assert due is False


def test_max_attempts_is_exposed_for_the_repository_query() -> None:
    policy = RetryBackoffPolicy(base_seconds=60, max_attempts=7)

    assert policy.max_attempts == 7
