"""`PostgresAuditLog`: `AuditLogPort` adapter over `audit_logs` (design.md
§4.3). `seq`/`prev_hash`/`row_hash` are left to the DB's hash-chain trigger
(`audit_hash_chain()`) -- this adapter never computes or sets them.

Same connection-ownership contract as every other Phase 3 postgres adapter
(see `consent_registry.py`'s docstring): takes an already-open
`AsyncConnection` from `app.db.runtime_engine` (the RLS-enforced
`app_runtime` role) with the request's GUCs already set, and writes within
the caller's existing transaction -- audit is only correct when it commits
atomically with the action it records (design.md §4.3).
"""

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
