import logging

from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditEntry

logger = logging.getLogger(__name__)


async def record_audit_best_effort(record_audit: AuditLogPort, entry: AuditEntry) -> None:
    """Calls `record_audit.record(entry)`; on any exception, logs it at
    WARNING level (with the stack trace) and returns normally instead of
    propagating. Callers await this as a fire-and-forget side effect that
    must never override the deny/throttle/budget decision already made."""
    try:
        await record_audit.record(entry)
    except Exception:
        logger.warning(
            "audit write failed for action=%s tenant_id=%s object_type=%s",
            entry.action,
            entry.tenant_id,
            entry.object_type,
            exc_info=True,
        )
