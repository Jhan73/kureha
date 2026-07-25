"""`TTLRotationReplayCache`: production `RotationReplayCachePort` impl, an
in-process `cachetools.TTLCache` -- same library/pattern already established
for design.md §18's availability cache (`cachetools.TTLCache`, bounded
`maxsize`, short TTL). See `RotationReplayCachePort`'s docstring for the
multi-instance limitation this deliberately accepts.

**No `tenant_id` prefix, deliberately (task 13.2's cache-invariant review):**
the key is `old_refresh_token_hash`, a cryptographic hash of a per-user
secret -- practically unique across tenants already, so a tenant prefix
would add no real isolation, only ceremony."""

from cachetools import TTLCache


class TTLRotationReplayCache:
    def __init__(self, *, ttl_seconds: float = 30, maxsize: int = 10_000) -> None:
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl_seconds)

    def get(self, old_refresh_token_hash: str) -> tuple[str, str] | None:
        return self._cache.get(old_refresh_token_hash)

    def set(self, old_refresh_token_hash: str, *, access_token: str, refresh_token: str) -> None:
        self._cache[old_refresh_token_hash] = (access_token, refresh_token)
