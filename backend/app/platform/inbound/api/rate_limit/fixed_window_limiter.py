"""`FixedWindowRateLimiter` (design.md §19, tasks.md task 5.3): orchestrates
`RateCounterStorePort` + `ClockPort` into a pass/fail decision for the
auth/token mint+refresh dimension -- "sliding/fixed-window sobre
`rate_counters` (§4.4) en Postgres -- UPSERT atomico por
`(dimension, subject, window_start)`".

`window_start` is computed here (in application code), not via a Postgres
`date_trunc` call, so the window size is not tied to a fixed SQL time unit
(minute/hour/day) -- a deterministic floor of the current epoch second to
the nearest `window_seconds` boundary, which two requests within the same
window always agree on regardless of which instance computes it."""

from datetime import datetime, timezone

from app.platform.inbound.api.rate_limit.rate_counter_store import RateCounterStorePort
from app.shared_kernel.clock import ClockPort


class FixedWindowRateLimiter:
    def __init__(self, counter_store: RateCounterStorePort, *, clock: ClockPort) -> None:
        self._counter_store = counter_store
        self._clock = clock

    async def check(
        self,
        *,
        dimension: str,
        subject: str,
        window_seconds: int,
        limit: int,
        tenant_id: str | None = None,
        by: int = 1,
    ) -> bool:
        """Increments the counter for the CURRENT window and returns
        whether the request is still within `limit` (i.e. the counter's new
        value, after this increment, is `<= limit`)."""
        window_start = self._window_start(window_seconds)
        new_count = await self._counter_store.increment(
            dimension=dimension,
            subject=subject,
            window_start=window_start,
            by=by,
            tenant_id=tenant_id,
        )
        return new_count <= limit

    def _window_start(self, window_seconds: int) -> datetime:
        now = self._clock.now()
        epoch_seconds = now.timestamp()
        floored = (epoch_seconds // window_seconds) * window_seconds
        return datetime.fromtimestamp(floored, tz=timezone.utc)
