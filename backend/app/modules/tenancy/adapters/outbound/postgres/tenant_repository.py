"""`PostgresTenantRepository`: `TenantRepositoryPort` adapter over `tenants`
(design.md §4.1, migration 8fc0dc6f958d).

Takes an already-open `AsyncConnection` rather than owning an engine, same
pattern every other postgres adapter in this codebase follows. `tenants` has
no RLS (migration 613f9ea3526f), so either `app.db.engine` or
`app.db.runtime_engine` is safe here -- the composition root (tasks.md task
10.2) may wire this against either, depending on whether the caller already
has a request-scoped connection or needs a pre-auth one (mirrors
`PostgresUserDirectory`'s elevated-connection note)."""

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
