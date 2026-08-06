from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.platform.inbound.api.access_control.live_actor import LiveActor

_SELECT = """
    SELECT u.id, u.tenant_id, u.site_id, u.role, u.status,
           u.patient_id, u.professional_id, sm.status AS staff_status
    FROM users u
    LEFT JOIN staff_members sm
      ON sm.tenant_id = u.tenant_id AND sm.site_id = u.site_id AND sm.user_id = u.id
    WHERE u.id = :user_id
"""


class PostgresLiveActorResolver:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def resolve(self, user_id: str) -> LiveActor | None:
        result = await self._conn.execute(text(_SELECT), {"user_id": user_id})
        row = result.first()
        if row is None:
            return None
        return LiveActor(
            user_id=str(row.id),
            tenant_id=str(row.tenant_id),
            site_id=str(row.site_id),
            role=row.role,
            status=row.status,
            patient_id=str(row.patient_id) if row.patient_id is not None else None,
            professional_id=str(row.professional_id) if row.professional_id is not None else None,
            staff_status=row.staff_status,
        )
