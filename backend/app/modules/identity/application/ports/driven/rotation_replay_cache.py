from typing import Protocol


class RotationReplayCachePort(Protocol):
    def get(self, old_refresh_token_hash: str) -> tuple[str, str] | None:
        """Returns `(access_token, refresh_token)` if this old hash was
        rotated within the cache's TTL, else `None`."""
        ...

    def set(self, old_refresh_token_hash: str, *, access_token: str, refresh_token: str) -> None: ...
