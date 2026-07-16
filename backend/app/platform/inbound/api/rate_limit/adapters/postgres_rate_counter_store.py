"""`PostgresRateCounterStore`: `RateCounterStorePort` adapter over
`rate_counters` (design.md §19). Same atomic UPSERT pattern proven in
`tests/schema/test_sessions_and_rate_limiting.py`:
`INSERT ... ON CONFLICT (dimension, subject, window_start) DO UPDATE SET
count = rate_counters.count + :by`. `peek` is a plain `SELECT` -- genuinely
side-effect-free, unlike calling `increment(..., by=0, ...)` as a fake-read
(which still creates a row via the UPSERT's `INSERT` branch).

`rate_counters` has no RLS (design.md §4.4) and is touched only by the
rate-limiting middleware, never a domain use case -- this adapter is wired
against `app.db.engine` (elevated), same as `PostgresLiveActorResolver`,
since the auth-throttle dimension runs pre-context (no `app.*` GUC exists
yet when a login/refresh attempt is being throttled)."""

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_UPSERT = """
    INSERT INTO rate_counters (tenant_id, dimension, subject, window_start, count)
    VALUES (:tenant_id, :dimension, :subject, :window_start, :by)
    ON CONFLICT (dimension, subject, window_start)
    DO UPDATE SET count = rate_counters.count + :by
    RETURNING count
"""

_SELECT = """
    SELECT count FROM rate_counters
    WHERE dimension = :dimension AND subject = :subject AND window_start = :window_start
"""


class PostgresRateCounterStore:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def increment(
        self,
        *,
        dimension: str,
        subject: str,
        window_start: datetime,
        by: int = 1,
        tenant_id: str | None = None,
    ) -> int:
        result = await self._conn.execute(
            text(_UPSERT),
            {
                "tenant_id": tenant_id,
                "dimension": dimension,
                "subject": subject,
                "window_start": window_start,
                "by": by,
            },
        )
        return result.scalar_one()

    async def peek(
        self,
        *,
        dimension: str,
        subject: str,
        window_start: datetime,
        tenant_id: str | None = None,
    ) -> int:
        result = await self._conn.execute(
            text(_SELECT),
            {"dimension": dimension, "subject": subject, "window_start": window_start},
        )
        row = result.scalar_one_or_none()
        return row if row is not None else 0
