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
