from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.identity.domain.refresh_session import RefreshSession

_SELECT = (
    "SELECT id, tenant_id, user_id, refresh_token_hash, issued_at, expires_at, "
    "rotated_from, revoked_at, last_used_at FROM user_sessions"
)


class PostgresSessionStore:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create(
        self,
        tenant_id: str,
        user_id: str,
        *,
        refresh_token_hash: str,
        expires_at: datetime,
        rotated_from: str | None = None,
    ) -> RefreshSession:
        result = await self._conn.execute(
            text(
                "INSERT INTO user_sessions (tenant_id, user_id, refresh_token_hash, expires_at, rotated_from) "
                "VALUES (:tenant_id, :user_id, :hash, :expires_at, :rotated_from) "
                "RETURNING id, tenant_id, user_id, refresh_token_hash, issued_at, expires_at, "
                "rotated_from, revoked_at, last_used_at"
            ),
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "hash": refresh_token_hash,
                "expires_at": expires_at,
                "rotated_from": rotated_from,
            },
        )
        return self._row_to_session(result.one())

    async def get_by_id(self, tenant_id: str, session_id: str) -> RefreshSession | None:
        result = await self._conn.execute(
            text(_SELECT + " WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": tenant_id, "id": session_id},
        )
        return self._row_to_session_or_none(result.first())

    async def find_by_hash(self, refresh_token_hash: str) -> RefreshSession | None:
        # Deliberately global (no tenant_id filter) -- see this method's
        # docstring on SessionStorePort.
        result = await self._conn.execute(
            text(_SELECT + " WHERE refresh_token_hash = :hash"), {"hash": refresh_token_hash}
        )
        return self._row_to_session_or_none(result.first())

    async def find_successor(self, session_id: str) -> RefreshSession | None:
        result = await self._conn.execute(
            text(_SELECT + " WHERE rotated_from = :id"), {"id": session_id}
        )
        return self._row_to_session_or_none(result.first())

    async def revoke(self, session_id: str, *, revoked_at: datetime) -> None:
        await self._conn.execute(
            text("UPDATE user_sessions SET revoked_at = :revoked_at WHERE id = :id AND revoked_at IS NULL"),
            {"id": session_id, "revoked_at": revoked_at},
        )

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
        # Single round trip: revoke the old row and insert its successor in
        # one statement via a data-modifying CTE (same style already
        # established by `revoke_chain` below).
        result = await self._conn.execute(
            text(
                """
                WITH revoked AS (
                    UPDATE user_sessions SET revoked_at = :revoked_at
                    WHERE id = :old_id AND revoked_at IS NULL
                )
                INSERT INTO user_sessions (tenant_id, user_id, refresh_token_hash, expires_at, rotated_from)
                VALUES (:tenant_id, :user_id, :hash, :expires_at, :old_id)
                RETURNING id, tenant_id, user_id, refresh_token_hash, issued_at, expires_at,
                    rotated_from, revoked_at, last_used_at
                """
            ),
            {
                "old_id": old_session_id,
                "revoked_at": revoked_at,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "hash": refresh_token_hash,
                "expires_at": expires_at,
            },
        )
        return self._row_to_session(result.one())

    async def revoke_chain(self, session_id: str, *, revoked_at: datetime) -> None:
        # Walk rotation lineage both ways; reuse detection revokes the whole chain.
        await self._conn.execute(
            text(
                """
                WITH RECURSIVE chain(id) AS (
                    SELECT id FROM user_sessions WHERE id = :id
                    UNION
                    SELECT s2.id
                    FROM chain c
                    JOIN user_sessions s1 ON s1.id = c.id
                    JOIN user_sessions s2
                      ON s2.id = s1.rotated_from OR s2.rotated_from = s1.id
                )
                UPDATE user_sessions SET revoked_at = :revoked_at
                WHERE id IN (SELECT id FROM chain) AND revoked_at IS NULL
                """
            ),
            {"id": session_id, "revoked_at": revoked_at},
        )

    async def revoke_all_for_user(self, tenant_id: str, user_id: str, *, revoked_at: datetime) -> int:
        # `rowcount` gives the matched-row count directly -- no need to
        # `RETURNING id` and transfer row data back just to `len()` it (fix,
        # confirmed review finding: redundant round trip / data transfer).
        result = await self._conn.execute(
            text(
                "UPDATE user_sessions SET revoked_at = :revoked_at "
                "WHERE tenant_id = :tenant_id AND user_id = :user_id AND revoked_at IS NULL"
            ),
            {"tenant_id": tenant_id, "user_id": user_id, "revoked_at": revoked_at},
        )
        return result.rowcount

    @staticmethod
    def _row_to_session_or_none(row) -> RefreshSession | None:
        if row is None:
            return None
        return PostgresSessionStore._row_to_session(row)

    @staticmethod
    def _row_to_session(row) -> RefreshSession:
        return RefreshSession(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            user_id=str(row.user_id),
            refresh_token_hash=row.refresh_token_hash,
            issued_at=row.issued_at,
            expires_at=row.expires_at,
            rotated_from=str(row.rotated_from) if row.rotated_from is not None else None,
            revoked_at=row.revoked_at,
            last_used_at=row.last_used_at,
        )
