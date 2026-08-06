from datetime import datetime
from typing import Protocol

from app.modules.identity.domain.refresh_session import RefreshSession


class SessionStorePort(Protocol):
    async def create(
        self,
        tenant_id: str,
        user_id: str,
        *,
        refresh_token_hash: str,
        expires_at: datetime,
        rotated_from: str | None = None,
    ) -> RefreshSession: ...

    async def get_by_id(self, tenant_id: str, session_id: str) -> RefreshSession | None:
        """Tenant-scoped PK lookup (logout/refresh use find_by_hash instead)."""
        ...

    async def find_by_hash(self, refresh_token_hash: str) -> RefreshSession | None:
        """Global lookup by hash — refresh token carries no tenant claim."""
        ...

    async def find_successor(self, session_id: str) -> RefreshSession | None:
        """Session that replaced this one via rotation; distinguishes rotation from other revokes."""
        ...

    async def revoke(self, session_id: str, *, revoked_at: datetime) -> None: ...

    async def rotate(
        self,
        old_session_id: str,
        tenant_id: str,
        user_id: str,
        *,
        refresh_token_hash: str,
        expires_at: datetime,
        revoked_at: datetime,
    ) -> RefreshSession:
        """Revoke old + create successor in one round trip."""
        ...

    async def revoke_chain(self, session_id: str, *, revoked_at: datetime) -> None:
        """Revoke session and full rotation lineage (ancestors and descendants)."""
        ...

    async def revoke_all_for_user(self, tenant_id: str, user_id: str, *, revoked_at: datetime) -> int:
        """Admin-revoke all sessions for user within tenant; returns count."""
        ...
