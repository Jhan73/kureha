"""CRITICAL fix #2 (fresh-review pass, kureha-mvp PR 6): `CheckRateLimit`
(`auth_rate_limit_middleware.py`) is `Callable[[str], Awaitable[bool]]`,
called positionally as `check_rate_limit(subject)`. `FixedWindowRateLimiter
.check` is keyword-only (`dimension`/`subject`/`window_seconds`/`limit`/
`tenant_id`/`by`) and cannot satisfy that shape directly.
`build_auth_ip_rate_limit_check` closes over a fixed `dimension="auth_ip"`,
`window_seconds`, and `limit`, exposing the single-positional-`str`-arg
shape `AuthRateLimitMiddleware` requires.

Wires a REAL `FixedWindowRateLimiter` (not a fake) to a fake
`RateCounterStorePort`, proving the adapter actually reaches
`FixedWindowRateLimiter.check` with the right dimension/window/limit --
`test_fixed_window_limiter.py` already proves the limiter's own math, this
test only proves the adapter's wiring."""

from datetime import datetime, timezone

from app.platform.inbound.api.rate_limit.auth_rate_limit_middleware import build_auth_ip_rate_limit_check
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
            {
                "dimension": dimension,
                "subject": subject,
                "window_start": window_start,
                "by": by,
                "tenant_id": tenant_id,
            }
        )
        key = (dimension, subject, window_start)
        self._counts[key] = self._counts.get(key, 0) + by
        return self._counts[key]


def _limiter(store: _FakeCounterStore) -> FixedWindowRateLimiter:
    return FixedWindowRateLimiter(store, clock=_FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))


async def test_adapter_reaches_the_limiter_with_the_configured_dimension_window_and_limit() -> None:
    store = _FakeCounterStore()
    limiter = _limiter(store)
    check_rate_limit = build_auth_ip_rate_limit_check(limiter, window_seconds=60, limit=5)

    allowed = await check_rate_limit("203.0.113.9")

    assert allowed is True
    assert len(store.calls) == 1
    assert store.calls[0]["dimension"] == "auth_ip"
    assert store.calls[0]["subject"] == "203.0.113.9"
    assert store.calls[0]["by"] == 1
    assert store.calls[0]["tenant_id"] is None


async def test_adapter_denies_once_the_configured_limit_is_exceeded() -> None:
    store = _FakeCounterStore()
    limiter = _limiter(store)
    check_rate_limit = build_auth_ip_rate_limit_check(limiter, window_seconds=60, limit=3)

    for _ in range(3):
        assert await check_rate_limit("203.0.113.9") is True

    assert await check_rate_limit("203.0.113.9") is False


async def test_adapter_keeps_independent_counters_per_subject() -> None:
    store = _FakeCounterStore()
    limiter = _limiter(store)
    check_rate_limit = build_auth_ip_rate_limit_check(limiter, window_seconds=60, limit=1)

    assert await check_rate_limit("203.0.113.9") is True
    assert await check_rate_limit("198.51.100.1") is True
