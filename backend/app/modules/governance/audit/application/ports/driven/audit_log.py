"""`AuditLogPort` (design.md §12): the driven port every use case that
writes an auditable action depends on. Implemented in MVP by
`PostgresAuditLog` (adapters/outbound/postgres/audit_log.py)."""

from typing import Protocol

from app.modules.governance.audit.domain.audit_entry import AuditEntry


class AuditLogPort(Protocol):
    async def record(self, entry: AuditEntry) -> str:
        """Writes one append-only audit row in the caller's current
        transaction (design.md §4.3: "write en la misma transaccion que la
        accion") and returns the new row's id."""
        ...
