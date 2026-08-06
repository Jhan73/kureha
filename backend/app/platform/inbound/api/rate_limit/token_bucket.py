from collections import OrderedDict

from app.shared_kernel.clock import ClockPort


class TokenBucket:
    def __init__(self, *, capacity: int, refill_per_second: float, clock: ClockPort) -> None:
        self._capacity = capacity
        self._refill_per_second = refill_per_second
        self._clock = clock
        self._tokens: float = float(capacity)
        self._last_refill = clock.now()

    def try_consume(self, amount: float = 1.0) -> bool:
        self._refill()
        if self._tokens < amount:
            return False
        self._tokens -= amount
        return True

    def _refill(self) -> None:
        now = self._clock.now()
        elapsed_seconds = (now - self._last_refill).total_seconds()
        if elapsed_seconds > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed_seconds * self._refill_per_second)
            self._last_refill = now


class TokenBucketRegistry:
    """Bounded LRU of TokenBuckets (eviction yields a fresh full bucket)."""

    def __init__(self, *, capacity: int, refill_per_second: float, clock: ClockPort, max_buckets: int = 10_000) -> None:
        self._capacity = capacity
        self._refill_per_second = refill_per_second
        self._clock = clock
        self._max_buckets = max_buckets
        self._buckets: OrderedDict[str, TokenBucket] = OrderedDict()

    def try_consume(self, key: str, amount: float = 1.0) -> bool:
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self._max_buckets:
                self._buckets.popitem(last=False)
            bucket = TokenBucket(capacity=self._capacity, refill_per_second=self._refill_per_second, clock=self._clock)
        self._buckets[key] = bucket
        self._buckets.move_to_end(key)
        return bucket.try_consume(amount)
