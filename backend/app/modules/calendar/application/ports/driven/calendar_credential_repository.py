"""`CalendarCredentialRepositoryPort` (design.md §4.4/§7.3, tasks.md task
9.4): calendar-module's own driven port over `calendar_credentials`.
Implemented in MVP by `PostgresCalendarCredentialRepository`
(adapters/outbound/postgres/calendar_credential_repository.py).

**RLS note for the composition root (Phase 10, not built):** `calendar_credentials`'
only policy, `calendar_credentials_self` (migration 613f9ea3526f), requires
`app.role = 'patient'` AND `app.patient_id` to equal the row's `patient_id`
for EVERY operation (SELECT/INSERT/UPDATE/DELETE alike) -- there is no
staff-facing policy. Every method on this port's Postgres adapter MUST be
called against a connection whose `app.*` GUCs are already set that way for
the target `patient_id` (mirrors `tests/rls/helpers.py`'s own
`seed_calendar_credential`, which sets `role="patient", patient_id=patient_id`
before writing). This is a REAL constraint on `SyncAppointmentToCalendar`
(application/use_cases/sync_appointment_to_calendar.py, tasks.md task 9.4),
which also needs to write `calendar_sync` under a DIFFERENT (staff-only)
role in the same flow -- see that module's docstring for the flagged
composition-root GUC-switching gap this implies."""

from typing import Protocol

from app.modules.calendar.domain.calendar_credential import EncryptedCredentialRecord
from app.modules.calendar.domain.encrypted_secret import EncryptedSecret


class CalendarCredentialRepositoryPort(Protocol):
    async def get(self, tenant_id: str, patient_id: str) -> EncryptedCredentialRecord | None:
        """Returns the patient's credential row (revoked or not -- callers
        check `.is_revoked` themselves), or `None` if the patient never
        connected a calendar at all."""
        ...

    async def save(
        self, tenant_id: str, patient_id: str, secret: EncryptedSecret, *, scope: str
    ) -> EncryptedCredentialRecord:
        """Upserts the patient's credential row (`UNIQUE (tenant_id,
        patient_id)`, migration 00d985a7bfa5) -- a patient reconnecting
        replaces their previous encrypted token rather than erroring."""
        ...

    async def revoke(self, tenant_id: str, patient_id: str) -> None:
        """Sets `revoked_at` and clears the encrypted token (design.md §7.3:
        "borrado del token cifrado")."""
        ...
