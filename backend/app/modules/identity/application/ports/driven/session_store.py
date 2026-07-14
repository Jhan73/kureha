"""`SessionStorePort` (design.md §17.4): `user_sessions` access for the
identity module's login/refresh/logout/admin-revoke use cases.

**Two different connection-privilege callers, one Protocol/adapter.**
`PostgresSessionStore` (adapters/outbound/postgres/session_store.py) takes a
plain `AsyncConnection`, same as every other Phase 3 postgres adapter -- but
WHICH engine backs that connection differs by use case:
- `Login`/`RefreshToken` run pre-auth (no `app.*` GUCs exist yet, same
  chicken-and-egg problem as `UserDirectoryPort` -- see that port's
  docstring) -> composition root wires these against `app.db.engine`
  (elevated).
- `Logout`/`RevokeAllSessionsForUser` run inside an already-authenticated
  request (Phase 5's access-control middleware has already resolved a
  `TenantContext` and set `app.*` GUCs) -> composition root wires these
  against `app.db.runtime_engine` (RLS-enforced `app_runtime`), same as
  every other business-module adapter.
"""

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
        """Tenant-scoped lookup by primary key. `Logout` does NOT use this
        (it hashes the caller's raw refresh token and looks up via
        `find_by_hash`, same as `RefreshToken` -- no client ever holds a raw
        `user_sessions.id`); kept for a future admin/session-listing use case
        that already has a resolved `TenantContext` and a known session id
        (e.g. displaying an audit trail)."""
        ...

    async def find_by_hash(self, refresh_token_hash: str) -> RefreshSession | None:
        """Global lookup, NOT tenant-scoped -- the caller does not know
        `tenant_id` yet at refresh time (an opaque refresh token carries no
        claims); `refresh_token_hash` is a cryptographically random,
        sufficiently long value, so a global search carries no meaningful
        collision risk in practice (design.md §17.4 does not specify a
        tenant-prefixed refresh-token format, and inventing one is out of
        this port's scope -- see apply-progress notes for the alternative
        considered)."""
        ...

    async def find_successor(self, session_id: str) -> RefreshSession | None:
        """Returns the session that replaced `session_id` via rotation --
        the row whose `rotated_from == session_id` -- or `None` if no such
        row exists. `RefreshSession` alone carries no revocation-cause field
        (only `revoked_at`), so `RefreshToken` uses this lookup to tell a
        genuine rotation-caused revocation (a successor exists) apart from
        any other revocation cause -- logout, admin-revoke, or the terminal
        node of an earlier reuse-detection chain-revoke (no successor).
        Security fix (design.md §17.4): the 30s rotation grace period must
        NEVER apply to the latter -- only to a real rotation replay."""
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
        """Revokes `old_session_id` and creates its successor in a single
        round trip -- the two writes have no data dependency the caller
        needs (the new row's `rotated_from` is already known before the
        revoke), so combining them avoids two sequential DB calls per
        refresh (mirrors the CTE style `revoke_chain` already uses)."""
        ...

    async def revoke_chain(self, session_id: str, *, revoked_at: datetime) -> None:
        """Revokes `session_id` and every session reachable from it via
        `rotated_from` links, in either direction (ancestors AND
        descendants) -- design.md §17.4's reuse-detection response: "revoca
        la cadena", not just the one presented row."""
        ...

    async def revoke_all_for_user(self, tenant_id: str, user_id: str, *, revoked_at: datetime) -> int:
        """Admin-revoke: every `user_sessions` row for this `user_id`,
        scoped to `tenant_id`, without touching any other user's sessions
        (spec `session-management` -> "Admin revokes a session"). Returns
        the number of rows revoked."""
        ...
