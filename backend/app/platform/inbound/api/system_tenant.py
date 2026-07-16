"""Well-known sentinel `tenant_id` for `audit_logs` rows emitted at a
platform checkpoint where no real tenant context has been established yet
(kureha-mvp PR 6, verify-report CRITICAL findings #2/#3, obs #414):

- `AuthRateLimitMiddleware` denies a request before any authentication has
  happened -- the pre-login `auth_ip` dimension genuinely has no tenant
  (design.md §4.4: "el limite pre-login por IP no tiene tenant aun";
  `rate_counters.tenant_id` is nullable for exactly this reason).
- `AccessControlMiddleware._audit_unmapped` can be reached by a
  cryptographically valid token whose `tenant_id` claim was never set at
  all (forged/malformed token; Kureha's own issuer always includes it).

`audit_logs.tenant_id` is `NOT NULL REFERENCES tenants(id)` (design.md
§4.1) -- there is no schema-level allowance for a tenant-less row, and
`AuditEntry.tenant_id: str` has no default. Widening either to accept
`None` would ripple across every module that constructs an `AuditEntry`
(governance/audit's whole write side), which is out of scope for this
narrow fix. This sentinel keeps both call sites satisfying their spec's
"MUST be auditable"/"MUST be recorded" requirement at the application
layer without changing `AuditEntry`'s shape or the `audit_logs` schema.

**Forward gap, not silently resolved:** an `INSERT` using this sentinel
will violate the real FK constraint until the composition root (task
10.2, not yet built) either seeds a reserved `tenants` row with this
exact id, or a future change relaxes the constraint for system-level
audit rows. Not exercised today because nothing wires a real
`AuditLogPort` Postgres adapter into these two middlewares yet -- both
are still driven by fakes/protocols pending the composition root, same
as `AuthRateLimitMiddleware.trust_forwarded_for`."""

SYSTEM_TENANT_ID = "00000000-0000-0000-0000-000000000000"
