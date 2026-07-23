"""Task 8.1: `Shift` domain (design.md §4.4/§6's `shifts` table shape). Pure
value object -- the actual anti-overlap write (`EXCLUDE USING gist`, design.md
§4.4) lives at the Postgres adapter/schema layer; this class only carries the
shape, mirroring `AvailabilitySlot`/`Appointment`."""

from datetime import datetime, timezone

from app.modules.staff.domain.shift import Shift

_T0 = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 8, 3, 14, 0, tzinfo=timezone.utc)


def test_shift_carries_its_fields() -> None:
    shift = Shift(id="sh1", tenant_id="t1", site_id="s1", staff_member_id="sm1", starts_at=_T0, ends_at=_T1)

    assert shift.id == "sh1"
    assert shift.tenant_id == "t1"
    assert shift.site_id == "s1"
    assert shift.staff_member_id == "sm1"
    assert shift.starts_at == _T0
    assert shift.ends_at == _T1
