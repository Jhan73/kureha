"""`StaffPolicy` (design.md §6: "StaffPolicy (baja no borra historia; shift
valido no solapa)"). Pure rules, no IO -- mirrors `RiskPolicy`/`TenantPolicy`/
`ConsentPolicy`'s "XPolicy = pure evaluator" convention (see
`consent_policy.py`'s module docstring, which names `StaffPolicy` as a sibling
of this same convention).

"Baja no borra historia" (deactivation never erases history) is NOT expressed
as a method here -- it is a structural guarantee of `StaffRepositoryPort`
itself, which deliberately has no delete method, only `deactivate_staff_
member` (a status flip persisting `deactivated_at`), the same precedent
`SchedulingRepositoryPort.cancel_appointment`'s docstring documents ("never
deletes the row"). `is_assignable` and `shifts_overlap` below are the two
rules that DO need pure, testable logic."""

from app.modules.staff.domain.shift import Shift
from app.modules.staff.domain.staff_member import StaffMember


class StaffPolicy:
    @staticmethod
    def is_assignable(staff: StaffMember) -> bool:
        """A deactivated staff member must never be assignable to a new
        shift (design.md §6; spec `staff-registry` -> "Deactivated staff
        cannot be scheduled")."""
        return staff.is_active

    @staticmethod
    def shifts_overlap(a: Shift, b: Shift) -> bool:
        """Pure interval-overlap predicate mirroring the semantics of the
        DB's `EXCLUDE USING gist (staff_member_id WITH =, tstzrange(...)
        WITH &&)` constraint (design.md §4.4) -- same staff member AND
        overlapping `[starts_at, ends_at)` ranges. The DB constraint remains
        the definitive, concurrency-safe floor (spec `staff-scheduling` ->
        "Concurrent shift edits do not create overlap"); this predicate is a
        pure, DB-free restatement of the same rule for callers/tests that
        don't need that guarantee."""
        if a.staff_member_id != b.staff_member_id:
            return False
        return a.starts_at < b.ends_at and b.starts_at < a.ends_at
