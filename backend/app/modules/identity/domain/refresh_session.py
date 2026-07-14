"""`RefreshSession` (design.md §17.4): projection of one `user_sessions`
row -- the shape `RefreshToken`/`Logout`/`RevokeAllSessionsForUser` operate
on. `rotated_from` links a session to the one it replaced (rotation chain);
`revoked_at` is set by logout, admin-revoke, or rotation itself."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RefreshSession:
    id: str
    tenant_id: str
    user_id: str
    refresh_token_hash: str
    issued_at: datetime
    expires_at: datetime
    rotated_from: str | None
    revoked_at: datetime | None
    last_used_at: datetime | None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None
