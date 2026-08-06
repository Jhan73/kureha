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
