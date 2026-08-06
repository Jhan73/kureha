from app.modules.staff.domain.shift import Shift
from app.modules.staff.domain.staff_member import StaffMember


class StaffPolicy:
    @staticmethod
    def is_assignable(staff: StaffMember) -> bool:
        """Deactivated staff must not get new shifts."""
        return staff.is_active

    @staticmethod
    def shifts_overlap(a: Shift, b: Shift) -> bool:
        """Same staff + overlapping [starts_at, ends_at); DB EXCLUDE is the race-safe floor."""
        if a.staff_member_id != b.staff_member_id:
            return False
        return a.starts_at < b.ends_at and b.starts_at < a.ends_at
