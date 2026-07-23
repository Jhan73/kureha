"""Task 8.1: `StaffPolicy` -- pure rules (design.md §6: "StaffPolicy (baja no
borra historia; shift valido no solapa)"). No IO -- the DB's own
`EXCLUDE USING gist` (design.md §4.4) remains the concurrency-safe floor for
overlap (see `PostgresShiftRepository`); `shifts_overlap` here is a pure
predicate usable standalone, mirroring `RiskPolicy`'s split between a pure
domain rule and its DB-level enforcement counterpart. `is_assignable` encodes
"deactivated staff MUST NOT be assignable to new ... shifts" (spec
`staff-registry` -> "Personnel Create/Deactivate per Site")."""

from datetime import datetime, timezone

from app.modules.staff.domain.shift import Shift
from app.modules.staff.domain.staff_member import OperationalRole, StaffMember, StaffStatus
from app.modules.staff.domain.staff_policy import StaffPolicy

_T0 = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 8, 3, 14, 0, tzinfo=timezone.utc)
_T2 = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
_T3 = datetime(2026, 8, 3, 18, 0, tzinfo=timezone.utc)


def _staff(*, status: StaffStatus) -> StaffMember:
    return StaffMember(
        id="sm1",
        tenant_id="t1",
        site_id="s1",
        user_id=None,
        professional_id="pr1",
        name="Ana Torres",
        operational_role=OperationalRole.PROFESSIONAL,
        status=status,
        activated_at=_T0,
        deactivated_at=None,
    )


def _shift(*, staff_member_id: str, starts_at: datetime, ends_at: datetime) -> Shift:
    return Shift(id="sh1", tenant_id="t1", site_id="s1", staff_member_id=staff_member_id, starts_at=starts_at, ends_at=ends_at)


def test_active_staff_is_assignable() -> None:
    assert StaffPolicy.is_assignable(_staff(status=StaffStatus.ACTIVE)) is True


def test_inactive_staff_is_not_assignable() -> None:
    assert StaffPolicy.is_assignable(_staff(status=StaffStatus.INACTIVE)) is False


def test_overlapping_shifts_for_the_same_staff_member_overlap() -> None:
    a = _shift(staff_member_id="sm1", starts_at=_T0, ends_at=_T1)
    b = _shift(staff_member_id="sm1", starts_at=_T2, ends_at=_T3)

    assert StaffPolicy.shifts_overlap(a, b) is True


def test_back_to_back_shifts_do_not_overlap() -> None:
    a = _shift(staff_member_id="sm1", starts_at=_T0, ends_at=_T1)
    b = _shift(staff_member_id="sm1", starts_at=_T1, ends_at=_T3)

    assert StaffPolicy.shifts_overlap(a, b) is False


def test_overlapping_windows_for_different_staff_members_do_not_overlap() -> None:
    a = _shift(staff_member_id="sm1", starts_at=_T0, ends_at=_T1)
    b = _shift(staff_member_id="sm2", starts_at=_T2, ends_at=_T3)

    assert StaffPolicy.shifts_overlap(a, b) is False
