"""`PatientEmailLookupPort` (design.md §7.3, tasks.md task 9.4): calendar's
own narrow driven port for the ONE read it needs from `patients` --
the patient's registered email, to compare against the OAuth-authorized
Google account's email (spec `google-calendar-sync` -> "Per-Patient OAuth
Using Registered Email").

`patients` is core identity schema (migration 8fc0dc6f958d), not privately
owned by any of the 5 business modules (unlike `staff_members`, which
`staff` genuinely encapsulates -- see `scheduling`'s `StaffStatusPort` for
that contrast, tasks.md task 8.4). This port still exists, rather than
having `ConnectPatientCalendar` read `patients` directly inline, for the
same reason `StaffStatusPort` does: the module that needs the read defines
a narrow port shaped around its own vocabulary (a bare email string), kept
swappable and independently fakeable in use-case tests -- not because
`patients` needs cross-module protection here."""

from typing import Protocol


class PatientEmailLookupPort(Protocol):
    async def get_registered_email(self, tenant_id: str, patient_id: str) -> str | None:
        """Returns the patient's registered email, or `None` if the patient
        has no email on file (`patients.email` is nullable, migration
        8fc0dc6f958d) -- callers treat `None` as "nothing to compare against",
        never as a mismatch by itself."""
        ...
