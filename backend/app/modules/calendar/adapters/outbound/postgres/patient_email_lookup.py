"""`PostgresPatientEmailLookup`: `PatientEmailLookupPort` adapter reading
`patients.email` (design.md §7.3, migration 8fc0dc6f958d). See the port's
own module docstring (application/ports/driven/patient_email_lookup.py) for
why calendar reads this table directly rather than going through another
module's port.

Takes an already-open `AsyncConnection`. `ConnectPatientCalendar` runs as
`role='patient'` (`patients_self`, migration 613f9ea3526f allows a patient
to SELECT their own row) -- the composition root (tasks.md task 10.2) MUST
construct this against a connection scoped that way."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class PostgresPatientEmailLookup:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get_registered_email(self, tenant_id: str, patient_id: str) -> str | None:
        result = await self._conn.execute(
            text("SELECT email FROM patients WHERE tenant_id = :tenant_id AND id = :patient_id"),
            {"tenant_id": tenant_id, "patient_id": patient_id},
        )
        row = result.first()
        return row.email if row is not None else None
