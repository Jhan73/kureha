from typing import Protocol

from app.modules.governance.audit.domain.audit_entry import AuditEntry


class AuditLogPort(Protocol):
    async def record(self, entry: AuditEntry) -> str:
        """Append-only write in the caller's current transaction; returns new row id."""
        ...
