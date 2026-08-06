from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.tenancy.domain.tenant import Tenant


class PostgresTenantRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get_by_id(self, tenant_id: str) -> Tenant | None:
        result = await self._conn.execute(
            text("SELECT id, name, status, llm_daily_budget_tokens FROM tenants WHERE id = :id"),
            {"id": tenant_id},
        )
        row = result.first()
        if row is None:
            return None
        return Tenant(
            id=str(row.id),
            name=row.name,
            status=row.status,
            llm_daily_budget_tokens=row.llm_daily_budget_tokens,
        )
