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
