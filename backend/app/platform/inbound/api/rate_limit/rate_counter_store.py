from datetime import datetime
from typing import Protocol


class RateCounterStorePort(Protocol):
    async def increment(
        self,
        *,
        dimension: str,
        subject: str,
        window_start: datetime,
        by: int = 1,
        tenant_id: str | None = None,
    ) -> int:
        """Atomically increments the counter for `(dimension, subject,
        window_start)` by `by` (creating the row with `count=by` if it
        doesn't exist yet) and returns the counter's new value."""
        ...

    async def peek(
        self,
        *,
        dimension: str,
        subject: str,
        window_start: datetime,
        tenant_id: str | None = None,
    ) -> int:
        """A genuine read of the current counter for `(dimension, subject,
        window_start)`, with NO side effect -- unlike `increment`, this
        never creates a row. Returns `0` when no row exists yet."""
        ...
