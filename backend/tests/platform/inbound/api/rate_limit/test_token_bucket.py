from datetime import datetime, timedelta, timezone

from app.platform.inbound.api.rate_limit.token_bucket import TokenBucket, TokenBucketRegistry


class _FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def test_bucket_starts_full_and_allows_up_to_capacity() -> None:
    clock = _FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    bucket = TokenBucket(capacity=3, refill_per_second=1.0, clock=clock)

    assert bucket.try_consume() is True
    assert bucket.try_consume() is True
    assert bucket.try_consume() is True
    assert bucket.try_consume() is False


def test_bucket_refills_over_time() -> None:
    clock = _FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    bucket = TokenBucket(capacity=2, refill_per_second=1.0, clock=clock)

    assert bucket.try_consume() is True
    assert bucket.try_consume() is True
    assert bucket.try_consume() is False

    clock.advance(timedelta(seconds=1))
    assert bucket.try_consume() is True


def test_bucket_never_refills_past_capacity() -> None:
    clock = _FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    bucket = TokenBucket(capacity=2, refill_per_second=1.0, clock=clock)

    clock.advance(timedelta(seconds=100))  # long idle period
    assert bucket.try_consume() is True
    assert bucket.try_consume() is True
    assert bucket.try_consume() is False


async def test_registry_gives_independent_buckets_per_key() -> None:
    clock = _FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    registry = TokenBucketRegistry(capacity=1, refill_per_second=1.0, clock=clock)

    assert registry.try_consume("tenant-a:patient-1") is True
    assert registry.try_consume("tenant-a:patient-1") is False
    # A different key has its own bucket, unaffected by the first.
    assert registry.try_consume("tenant-a:patient-2") is True


async def test_registry_reuses_the_same_bucket_for_the_same_key() -> None:
    clock = _FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    registry = TokenBucketRegistry(capacity=5, refill_per_second=1.0, clock=clock)

    for _ in range(5):
        assert registry.try_consume("tenant-a:patient-1") is True
    assert registry.try_consume("tenant-a:patient-1") is False


async def test_registry_evicts_the_least_recently_used_bucket_once_over_max_buckets() -> None:
    clock = _FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    registry = TokenBucketRegistry(capacity=1, refill_per_second=1.0, clock=clock, max_buckets=2)

    assert registry.try_consume("key-a") is True  # key-a bucket created, empty
    assert registry.try_consume("key-b") is True  # key-b bucket created, empty
    # key-a is now the least-recently-used of the two -- creating a third
    # key must evict it, not key-b.
    assert registry.try_consume("key-c") is True  # over capacity -> evict key-a

    # key-b was NOT evicted -> its bucket is still empty (capacity=1, already
    # consumed once above), so this must fail. Checked BEFORE re-touching
    # key-a below, since re-adding key-a would itself trigger another
    # eviction (only 2 slots exist) and confuse which key survived.
    assert registry.try_consume("key-b") is False
    # key-a was evicted -> a fresh bucket is created for it, starting full
    # again (capacity=1, so this consume succeeds).
    assert registry.try_consume("key-a") is True


async def test_registry_accessing_an_existing_key_refreshes_its_recency() -> None:
    clock = _FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    registry = TokenBucketRegistry(capacity=1, refill_per_second=1.0, clock=clock, max_buckets=2)

    registry.try_consume("key-a")
    registry.try_consume("key-b")
    # Touch key-a again so it becomes the most-recently-used, leaving key-b
    # as the least-recently-used.
    registry.try_consume("key-a")

    registry.try_consume("key-c")  # over capacity -> evict key-b, not key-a

    # key-a was NOT evicted -> its bucket is still empty. Checked BEFORE
    # re-adding key-b below, since re-adding it would itself trigger
    # another eviction (only 2 slots exist).
    assert registry.try_consume("key-a") is False
    # key-b was evicted -> fresh bucket, starts full again.
    assert registry.try_consume("key-b") is True


async def test_registry_default_max_buckets_is_ten_thousand() -> None:
    clock = _FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    registry = TokenBucketRegistry(capacity=1, refill_per_second=1.0, clock=clock)

    assert registry._max_buckets == 10_000
