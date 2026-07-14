"""`RotationReplayCachePort` (design.md §17.4's 30s grace period): caches the
(access_token, refresh_token) pair just minted by a rotation, keyed by the
OLD refresh token's hash, so a network-retry that replays the old refresh
token within the grace window gets back the exact SAME pair instead of a
second, different rotation (design.md: "responde con el mismo token nuevo ya
emitido -- idempotencia de rotacion").

**In-process only, same class of tradeoff as the §18 availability
TTLCache** -- NOT shared across ECS Fargate instances (design.md §20, no
ElastiCache in MVP). A retry landing on a DIFFERENT instance than the one
that performed the original rotation is a cache miss here; `RefreshToken`'s
documented fallback for a miss during an otherwise-valid grace-period replay
is to perform a SECOND rotation from the already-rotated successor session,
which is still functionally correct (the client receives a valid, working
new token pair) but not byte-identical to the first response. This is an
accepted, explicitly flagged limitation -- fixing it for real requires a
shared cache (Redis/ElastiCache), out of MVP's infra budget (design.md §20).
"""

from typing import Protocol


class RotationReplayCachePort(Protocol):
    def get(self, old_refresh_token_hash: str) -> tuple[str, str] | None:
        """Returns `(access_token, refresh_token)` if this old hash was
        rotated within the cache's TTL, else `None`."""
        ...

    def set(self, old_refresh_token_hash: str, *, access_token: str, refresh_token: str) -> None: ...
