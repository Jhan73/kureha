from typing import Protocol

from app.modules.governance.audit.domain.audit_entry import AuditEntry


class IsolatedAuditLogPort(Protocol):
    async def record_best_effort(self, entry: AuditEntry) -> None:
        """Write on an isolated connection; never raise."""
        ...
