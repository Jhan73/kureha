"""`TokenBucket`/`TokenBucketRegistry` (design.md §19, tasks.md task 5.3b):
per-instance, in-process token-bucket rate limiting for the patient chat
endpoint -- "token-bucket per-instance keyed por tenant+patient... se evita
un write a store compartido por mensaje". Deliberately NOT backed by a
shared store (ADR-17: "la unica dimension que exige exactitud
cross-instancia es la de auth... el chat, de alta frecuencia, solo necesita
acotar costo, no exactitud")."""

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
    """A genuinely bounded registry of one `TokenBucket` per key (e.g.
    `f"{tenant_id}:{patient_id}"`), all sharing the same capacity/refill
    rate and clock -- lazily creates a bucket the first time a key is seen,
    reuses it thereafter.

    **Bounded via LRU eviction, capped at `max_buckets`:** an
    `OrderedDict` tracks last-access order (a key is moved to the end on
    every access/creation); once creating a new bucket would exceed
    `max_buckets`, the least-recently-used bucket is evicted first (popped
    from the front). An evicted bucket's patient simply gets a fresh, full
    bucket on their next message -- acceptable per design.md ADR-17: this
    dimension only needs to "acotar costo" (bound memory/cost), not
    exactness."""

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
