"""`ClockPort`: the only sanctioned way to read "now" in domain/application
code (design.md §2.5). Never call `datetime.now()`/`datetime.utcnow()`
directly from a use case -- inject this port instead, so tests can supply a
deterministic fake without monkeypatching the stdlib.
"""

from datetime import datetime, timezone
from typing import Protocol


class ClockPort(Protocol):
    def now(self) -> datetime:
        """Returns the current instant as a timezone-aware UTC datetime."""
        ...


class SystemClock:
    """The only production implementation -- trivial enough that, per
    design.md §2.5, it does not warrant its own module."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)
