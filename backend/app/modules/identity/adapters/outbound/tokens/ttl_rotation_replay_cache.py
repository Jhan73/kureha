from cachetools import TTLCache


class TTLRotationReplayCache:
    def __init__(self, *, ttl_seconds: float = 30, maxsize: int = 10_000) -> None:
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl_seconds)

    def get(self, old_refresh_token_hash: str) -> tuple[str, str] | None:
        return self._cache.get(old_refresh_token_hash)

    def set(self, old_refresh_token_hash: str, *, access_token: str, refresh_token: str) -> None:
        self._cache[old_refresh_token_hash] = (access_token, refresh_token)
