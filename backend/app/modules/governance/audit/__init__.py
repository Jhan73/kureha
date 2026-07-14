"""Audit module: `AuditEntry`/`AuditAction`/`AuditActorType` domain,
`AuditLogPort`, `PostgresAuditLog` adapter writing to the hash-chained
append-only `audit_logs` table (design.md §4.3)."""
