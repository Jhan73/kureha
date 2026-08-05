"""`IsolatedAuditLogPort`: a best-effort audit write that is CONNECTION-
ISOLATED from whatever transaction the caller's own primary decision runs
on -- distinct from `AuditLogPort` (audit_log.py), which deliberately writes
"in the caller's current transaction" (that module's own docstring, design.md
§4.3's "write en la misma transaccion que la accion").

**Why a second port exists at all, not just `AuditLogPort` +
`audit_safety.record_audit_best_effort`:** `record_audit_best_effort`
catches and swallows a failure from the audit write itself, but that is only
sufficient when the audit write runs on a connection/transaction nothing
else still needs. `CompletePasswordReset._deny_unmapped` is the CONFIRMED
counter-example (fresh-review finding, this batch): it wrote the
`AUTH_UNMAPPED_IDENTITY` entry through a plain `AuditLogPort` bound to the
SAME connection `user_directory`/`session_store` use, with a caller-supplied,
never-validated `tenant_id` (`PasswordResetConfirmRequest.tenant_id`). A
bogus `tenant_id` makes the audit INSERT itself violate `audit_logs`' real
`NOT NULL REFERENCES tenants(id)` FK -- and on a SHARED connection, Postgres
marks the WHOLE transaction aborted the instant that happens, so catching the
exception with `record_audit_best_effort` does not help: the transaction is
already poisoned, and the caller's own subsequent work (or COMMIT) on that
connection fails too. `routers/auth.py`'s `_check_and_audit_account_rate_limit`
proved the fix empirically for the exact same hazard on a different call
site: give the audit write its OWN, separately-opened connection, so a
failure there can only ever affect ITS OWN, throwaway connection/transaction.

`IsolatedAuditLogPort` generalizes that proven mechanism into an injectable
port, so an application-layer use case (`CompletePasswordReset`) can depend
on it without importing `AsyncConnection`/`open_elevated_connection`/the
composition root directly (backend/AGENTS.md's hexagonal boundary -- use
cases depend on ports, never on `app.composition_root`, which would also be
a circular import: `composition_root` itself imports every use case).
`ElevatedIsolatedAuditLog` (composition_root.py) is the concrete
implementation, mirroring `_check_and_audit_account_rate_limit`'s two-
connection pattern exactly."""

from typing import Protocol

from app.modules.governance.audit.domain.audit_entry import AuditEntry


class IsolatedAuditLogPort(Protocol):
    async def record_best_effort(self, entry: AuditEntry) -> None:
        """Records `entry` on its OWN, independent connection/transaction --
        never the same connection/transaction as the caller's primary
        decision -- and NEVER raises: any failure (including the audit
        INSERT itself violating a constraint) is logged and swallowed,
        exactly like `audit_safety.record_audit_best_effort`, but with the
        added guarantee that the failure cannot poison a connection/
        transaction anything else still needs."""
        ...
