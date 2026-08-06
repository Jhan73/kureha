from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    """Decoded JWT claims; untrusted for authz until re-resolved against live users row."""

    sub: str | None
    tenant_id: str | None
    site_id: str | None
    role: str | None


class AccessTokenVerifierPort(Protocol):
    def verify(self, token: str) -> AccessTokenClaims | None:
        """Claims if valid; None for any failure (callers only need reject/refresh)."""
        ...
