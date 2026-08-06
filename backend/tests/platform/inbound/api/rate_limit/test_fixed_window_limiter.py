from datetime import datetime, timezone

from app.platform.inbound.api.rate_limit.fixed_window_limiter import FixedWindowRateLimiter


class _FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class _FakeCounterStore:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._counts: dict[tuple, int] = {}

    async def increment(self, *, dimension, subject, window_start, by=1, tenant_id=None) -> int:
        self.calls.append(
            {"dimension": dimension, "subject": subject, "window_start": window_start, "by": by, "tenant_id": tenant_id}
        )
        key = (dimension, subject, window_start)
        self._counts[key] = self._counts.get(key, 0) + by
        return self._counts[key]


async def test_allows_requests_under_the_limit() -> None:
    store = _FakeCounterStore()
    limiter = FixedWindowRateLimiter(store, clock=_FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))

    allowed = await limiter.check(dimension="auth_ip", subject="1.2.3.4", window_seconds=60, limit=5)
    assert allowed is True


async def test_denies_requests_once_the_limit_is_exceeded() -> None:
    store = _FakeCounterStore()
    limiter = FixedWindowRateLimiter(store, clock=_FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))

    for _ in range(5):
        assert await limiter.check(dimension="auth_ip", subject="1.2.3.4", window_seconds=60, limit=5) is True

    assert await limiter.check(dimension="auth_ip", subject="1.2.3.4", window_seconds=60, limit=5) is False


async def test_different_subjects_have_independent_counters() -> None:
    store = _FakeCounterStore()
    limiter = FixedWindowRateLimiter(store, clock=_FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))

    for _ in range(5):
        await limiter.check(dimension="auth_ip", subject="1.2.3.4", window_seconds=60, limit=5)

    # A different subject starts its own counter from zero.
    assert await limiter.check(dimension="auth_ip", subject="5.6.7.8", window_seconds=60, limit=5) is True


async def test_window_start_is_a_deterministic_floor_of_now_to_window_seconds() -> None:
    store = _FakeCounterStore()
    # 12:00:35 UTC floored to a 60s window -> 12:00:00 UTC.
    now = datetime(2026, 1, 1, 12, 0, 35, tzinfo=timezone.utc)
    limiter = FixedWindowRateLimiter(store, clock=_FixedClock(now))

    await limiter.check(dimension="auth_ip", subject="1.2.3.4", window_seconds=60, limit=5)

    assert store.calls[0]["window_start"] == datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


async def test_two_requests_in_the_same_window_floor_to_the_same_bucket() -> None:
    store = _FakeCounterStore()
    now_a = datetime(2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc)
    now_b = datetime(2026, 1, 1, 12, 0, 55, tzinfo=timezone.utc)

    limiter_a = FixedWindowRateLimiter(store, clock=_FixedClock(now_a))
    await limiter_a.check(dimension="auth_ip", subject="1.2.3.4", window_seconds=60, limit=5)

    limiter_b = FixedWindowRateLimiter(store, clock=_FixedClock(now_b))
    await limiter_b.check(dimension="auth_ip", subject="1.2.3.4", window_seconds=60, limit=5)

    assert store.calls[0]["window_start"] == store.calls[1]["window_start"]


async def test_passes_tenant_id_through_to_the_counter_store() -> None:
    store = _FakeCounterStore()
    limiter = FixedWindowRateLimiter(store, clock=_FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))

    await limiter.check(dimension="llm_tokens", subject="t1", window_seconds=86400, limit=100_000, tenant_id="t1")

    assert store.calls[0]["tenant_id"] == "t1"
