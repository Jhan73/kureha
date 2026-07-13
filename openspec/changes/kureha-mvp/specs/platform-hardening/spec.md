# Platform Hardening Specification (platform-hardening)

## Purpose

Cross-cutting platform security requirements that a system handling sensitive clinical data cannot defer: rate limiting on exposed endpoints, safe caching, and the security constraints an AWS deployment must satisfy. This spec states requirements and constraints, not a concrete topology — deployment architecture (VPC/ECS/RDS/etc.) is `sdd-design`'s responsibility.

## Requirements

### Requirement: Rate Limiting on Authentication Endpoints

The system MUST rate-limit authentication endpoints (login, token exchange, password reset) by tenant, IP, and user/account, independent of whether authentication is delegated to an external identity provider. Exceeding the limit MUST result in a temporary denial, not a silent pass-through.

#### Scenario: Brute-force login attempts throttled

- GIVEN repeated failed login attempts against the same account or IP within a short window
- WHEN the configured threshold is exceeded
- THEN further attempts MUST be rejected until the window resets, and the throttling event MUST be auditable

### Requirement: Rate Limiting on Patient Chat

The system MUST rate-limit the patient-facing chat endpoint by tenant, IP, and patient, to contain abuse and bound LLM cost exposure.

#### Scenario: Excessive chat requests throttled

- GIVEN a single patient/session sends requests far above normal conversational cadence
- WHEN the configured threshold is exceeded
- THEN further requests MUST be rejected or queued until the window resets, without silently absorbing unbounded cost

### Requirement: Tenant-Scoped Cache Never Serves RLS-Denied Data

Any cache used for availability lookups, RBAC resolution, or copilot tool results MUST be scoped per tenant and MUST NOT ever return data that a live RLS check would deny for the requesting actor. Cache invalidation on permission change MUST be correct (see `action-based-rbac` for the RBAC-specific hard requirement).

#### Scenario: Cache entry never crosses tenants

- GIVEN a cache entry computed for tenant T1
- WHEN a request from tenant T2 would otherwise match the same cache key
- THEN the cache key MUST be tenant-scoped so T2 never receives T1's cached result

### Requirement: Encryption in Transit

All network traffic carrying patient data, credentials, or tokens MUST be encrypted in transit (TLS); no endpoint handling such data MUST accept plaintext connections.

#### Scenario: Plaintext connection rejected

- GIVEN a client attempts to connect without TLS to an endpoint carrying patient or credential data
- WHEN the connection is attempted
- THEN it MUST be rejected or upgraded — it MUST NOT be served in plaintext

### Requirement: Secrets Are Never Stored in Plaintext or Environment Variables

Long-lived secrets (database credentials, the KEK used for calendar-token envelope encryption per `google-calendar-sync`, IdP client secrets) MUST be stored in a dedicated secret-management mechanism, never committed to source, hardcoded, or passed as plaintext environment variables in a way that leaves them recoverable from process inspection or deployment artifacts.

#### Scenario: Secret retrieved at runtime, not baked in

- GIVEN a running service instance needs the KEK
- WHEN it starts up
- THEN it MUST retrieve the secret from the secret-management mechanism at runtime — the secret MUST NOT be baked into the deployment artifact or plaintext config

### Requirement: Least-Privilege Infrastructure Access

Infrastructure components (compute, database, secret store) MUST be granted only the minimum permissions required for their function; the database MUST NOT be reachable from outside the application's private network boundary.

#### Scenario: Database not publicly reachable

- GIVEN the production database
- WHEN network reachability is tested from outside the private application network
- THEN the database MUST be unreachable

### Requirement: Descriptive, Non-Leaky Error Taxonomy

User-facing errors across the chat and API surface MUST be specific enough to give the user precise, actionable context, distinguishing at minimum: authentication errors, validation errors, calendar-sync-degraded (best-effort per `google-calendar-sync` — communicated as a degraded-sync state, not a blocking failure), HITL-pending (per `clinical-safety`'s human-in-the-loop requirement), clinical-scope-refused (per `clinical-scope-validator`), and rate-limited (per this spec's rate-limiting requirements). Regardless of error type, the user-facing message MUST NOT leak internal implementation details — no stack traces, exception class names, database error text, secrets, internal identifiers, or infrastructure information may appear in the message shown to the user.

#### Scenario: Calendar-sync degradation communicated as a status, not a blocking error

- GIVEN a Google Calendar sync attempt fails after the appointment is already confirmed in Kureha
- WHEN the user views the result
- THEN they MUST see a specific "calendar sync degraded" message, not a generic error, and the appointment MUST still show as confirmed

#### Scenario: Internal details never reach the user-facing message

- GIVEN any error occurs during a chat or API request (validation, auth, rate-limit, or an unexpected failure)
- WHEN the error is surfaced to the user
- THEN the message MUST NOT include stack traces, exception class names, database error text, secrets, or infrastructure details

#### Scenario: Distinct error types are distinguishable by the user

- GIVEN a user encounters a validation error and, separately, a rate-limited request
- WHEN each error is shown
- THEN the messages MUST be distinguishable from one another — not a single generic "something went wrong" for both
