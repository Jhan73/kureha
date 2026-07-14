"""Task 4.4: `TTLRotationReplayCache` -- production `RotationReplayCachePort`
impl, in-process `cachetools.TTLCache` (see that port's docstring for the
multi-instance limitation this accepts)."""

import time

from app.modules.identity.adapters.outbound.tokens.ttl_rotation_replay_cache import TTLRotationReplayCache


def test_set_then_get_returns_the_cached_pair() -> None:
    cache = TTLRotationReplayCache(ttl_seconds=30, maxsize=100)

    cache.set("old-hash", access_token="access-1", refresh_token="refresh-1")

    assert cache.get("old-hash") == ("access-1", "refresh-1")


def test_get_returns_none_for_an_unknown_key() -> None:
    cache = TTLRotationReplayCache(ttl_seconds=30, maxsize=100)
    assert cache.get("never-set") is None


def test_entries_expire_after_the_configured_ttl() -> None:
    cache = TTLRotationReplayCache(ttl_seconds=0.05, maxsize=100)
    cache.set("old-hash", access_token="access-1", refresh_token="refresh-1")

    time.sleep(0.1)

    assert cache.get("old-hash") is None


def test_maxsize_is_bounded() -> None:
    cache = TTLRotationReplayCache(ttl_seconds=30, maxsize=2)
    cache.set("a", access_token="x", refresh_token="y")
    cache.set("b", access_token="x", refresh_token="y")
    cache.set("c", access_token="x", refresh_token="y")

    assert len(cache._cache) <= 2  # noqa: SLF001 -- whitebox bound check
