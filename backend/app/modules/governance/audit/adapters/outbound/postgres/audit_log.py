import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.governance.audit.domain.audit_entry import AuditEntry


class PostgresAuditLog:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def record(self, entry: AuditEntry) -> str:
        # asyncpg has no built-in codec for a plain Python dict -> jsonb --
        # serialize explicitly and cast server-side, same as any other
        # jsonb write over asyncpg's raw protocol.
        result = await self._conn.execute(
            text(
                "INSERT INTO audit_logs "
                "(tenant_id, site_id, actor_id, actor_type, action, object_type, "
                "object_id, reason, approval_id, payload) "
                "VALUES (:tenant_id, :site_id, :actor_id, :actor_type, :action, :object_type, "
                ":object_id, :reason, :approval_id, CAST(:payload AS jsonb)) "
                "RETURNING id"
            ),
            {
                "tenant_id": entry.tenant_id,
                "site_id": entry.site_id,
                "actor_id": entry.actor_id,
                "actor_type": entry.actor_type.value,
                "action": entry.action.value,
                "object_type": entry.object_type,
                "object_id": entry.object_id,
                "reason": entry.reason,
                "approval_id": entry.approval_id,
                "payload": json.dumps(entry.payload),
            },
        )
        return str(result.scalar_one())
