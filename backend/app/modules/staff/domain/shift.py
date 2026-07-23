"""`Shift` domain (design.md §4.4/§6's `shifts` table shape). Pure value
object, no IO -- mirrors `AvailabilitySlot`/`Appointment`. The anti-overlap
write (`EXCLUDE USING gist`, design.md §4.4) is enforced at the Postgres
adapter/schema layer (see `PostgresShiftRepository`); `StaffPolicy.
shifts_overlap` offers the same rule as a pure predicate for callers that
don't want to round-trip the DB."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Shift:
    id: str
    tenant_id: str
    site_id: str
    staff_member_id: str
    starts_at: datetime
    ends_at: datetime
