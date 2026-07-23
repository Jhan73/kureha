"""`RetryBackoffPolicy` (design.md §7.5, tasks.md task 9.5): pure, IO-free
backoff/attempts-cap rule for the calendar-sync retry/reconciliation job.
Kept as a domain value the same way `RiskPolicy`/`StaffPolicy` are -- fully
unit-testable without a clock port or a database, exercised by
`RetryPendingCalendarSyncs` (application/use_cases/retry_pending_calendar_syncs.py),
which supplies `now` from `ClockPort` and `updated_at`/`attempts` from each
`CalendarSyncRecord` returned by `CalendarSyncRepositoryPort.list_due_for_retry`.

Backoff grows exponentially with `attempts` (`base_seconds * 2**attempts`) --
a job with a few failures waits longer between retries, bounded by
`max_attempts` so a permanently-broken sync (e.g. a revoked credential)
eventually stops being retried at all (design.md §7.5: "agota -> queda
`failed` auditado, no bloquea nada")."""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class RetryBackoffPolicy:
    base_seconds: int = 60
    max_attempts: int = 5

    def is_due(self, *, attempts: int, updated_at: datetime, now: datetime) -> bool:
        if attempts >= self.max_attempts:
            return False
        backoff = timedelta(seconds=self.base_seconds * (2**attempts))
        return now >= updated_at + backoff
