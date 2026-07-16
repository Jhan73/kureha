"""Best-effort audit write helper, deduplicated out of
`AccessControlMiddleware`, `AuthRateLimitMiddleware`, and `LlmBudgetGuard`
(fresh-review pass CRITICAL fixes #1/#3, kureha-mvp PR 6): every platform
checkpoint that audits a DENY/throttled/budget-exceeded decision must never
let a failure in the audit write itself replace that decision with an
unhandled 500 (or, for `LlmBudgetGuard`, mask the `LlmBudgetExceededError`
callers specifically expect to catch).

A concrete, non-hypothetical failure mode this guards against: `_record_audit
.record(...)` for `AUTH_UNMAPPED_IDENTITY`/`AUTH_RATE_LIMITED` writes under
the `SYSTEM_TENANT_ID` sentinel (`system_tenant.py`), which has no seeded
`tenants` row yet -- a real Postgres `AuditLogPort` adapter would raise an
FK violation there today. The security/rate-limit/budget decision ALWAYS
wins over the audit trail: if `record()` raises, the failure is logged and
swallowed here, never propagated to the caller."""

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
