"""Task 3.1: `ClockPort`/`SystemClock` (design.md §2.5)."""

from datetime import timezone

from app.shared_kernel.clock import SystemClock


def test_system_clock_returns_timezone_aware_utc_datetime() -> None:
    clock = SystemClock()

    now = clock.now()

    assert now.tzinfo is not None
    assert now.utcoffset() == timezone.utc.utcoffset(now)


def test_system_clock_now_advances() -> None:
    clock = SystemClock()

    first = clock.now()
    second = clock.now()

    assert second >= first
