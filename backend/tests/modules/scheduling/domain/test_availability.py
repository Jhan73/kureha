"""Task 7.1: `AvailabilitySlot` domain (design.md §4.1's `availability` table
shape). Pure value object, no IO."""

from datetime import datetime, timezone

from app.modules.scheduling.domain.availability import AvailabilitySlot, AvailabilityStatus

_T0 = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)


def _slot(*, status: AvailabilityStatus = AvailabilityStatus.AVAILABLE) -> AvailabilitySlot:
    return AvailabilitySlot(
        id="av1",
        tenant_id="t1",
        site_id="s1",
        professional_id="pr1",
        starts_at=_T0,
        ends_at=_T1,
        status=status,
    )


def test_is_available_when_status_is_available() -> None:
    assert _slot(status=AvailabilityStatus.AVAILABLE).is_available is True


def test_is_not_available_when_reserved() -> None:
    assert _slot(status=AvailabilityStatus.RESERVED).is_available is False


def test_is_not_available_when_blocked() -> None:
    assert _slot(status=AvailabilityStatus.BLOCKED).is_available is False
