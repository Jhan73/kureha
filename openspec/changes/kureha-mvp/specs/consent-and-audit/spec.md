# Consent and Audit Specification (versioned-consent, append-only-audit-log)

## Purpose

Consent as a versioned precondition for processing patient data, and an immutable audit trail of every state-changing action. This spec defines the MECHANISM only.

> **MUST-clarify (pending business input)**: the exact accepted-scope wording, consent text, and retention duration are NOT defined here — they are a pending legal/business input. This spec does not fabricate legal copy; it defines how consent is captured, versioned, and checked.

## Requirements

### Requirement: Consent as Precondition

The system MUST verify the patient has an active consent record referencing a known policy version before processing any request touching patient health data. The system MUST NOT process such data when consent is absent, expired, or superseded by a newer unaccepted version.

#### Scenario: Valid current consent

- GIVEN a patient with an accepted consent at the current policy version
- WHEN a data-touching request arrives
- THEN processing proceeds normally

#### Scenario: Missing consent

- GIVEN a patient with no consent record
- WHEN they request scheduling help
- THEN the system MUST refuse to process patient data
- AND MUST prompt the patient to complete the consent flow before continuing

#### Scenario: Consent version changes mid-conversation

- GIVEN an active conversation and the policy version is bumped between turns
- WHEN the next data-touching action is attempted
- THEN the system MUST detect the version mismatch and halt further processing
- AND MUST request re-consent before continuing
- AND actions completed before invalidation remain valid and audited

#### Scenario: Consent revoked

- GIVEN a patient revokes consent
- WHEN a new request for that patient arrives
- THEN the system MUST stop processing new requests immediately
- AND existing appointments are unaffected unless the patient separately requests cancellation

### Requirement: Consent Versioning and Storage

Each consent record MUST store a version identifier, timestamp, and channel of acceptance. The system MUST NOT accept a consent action without an associated version.

#### Scenario: Consent recorded with version

- GIVEN a patient accepts consent
- WHEN the record is stored
- THEN it MUST include version id, timestamp, and acceptance channel

### Requirement: Append-Only Audit Log

The system MUST record every state-changing action (schedule, reschedule, cancel, consent event, RLS denial, RBAC denial, HITL decision, staff/shift change, calendar-sync outcome) to `audit_logs` in the same transaction as the action. Every row MUST include `tenant_id` so audit trails remain isolable per clinic. The system MUST NOT allow UPDATE or DELETE on existing audit rows.

#### Scenario: Action recorded atomically

- GIVEN an agent creates an appointment
- WHEN the transaction commits
- THEN an audit row with actor, `tenant_id`, timestamp, motivo, and resultado is committed together with it

#### Scenario: Failed action leaves no phantom trace

- GIVEN a transaction fails and rolls back
- WHEN the rollback occurs
- THEN the associated audit row MUST also roll back — no partial trace of an action that never happened

#### Scenario: Correcting a wrong entry

- GIVEN a wrong audit entry is discovered later
- WHEN it needs correction
- THEN the system MUST NOT delete or edit the row
- AND MUST insert a compensating event referencing the original row id

### Requirement: Tamper-Evident Chain

The audit log SHOULD hash-chain each row (hash includes the previous row's hash) so tampering is detectable.

#### Scenario: Chain integrity check

- GIVEN the audit log has N rows
- WHEN an integrity check recomputes the hash chain
- THEN any out-of-band row modification MUST break the chain and be detected

### Requirement: Hash-Chain Integrity Monitoring and Alerting

The system MUST run a periodic integrity verification job that recomputes the hash chain (per tenant) and MUST raise an alert when a break (tampered or missing row) is detected — silent failure is not acceptable. The system MUST also detect if the verification job itself stops running (dead-man's switch), and MUST alert on that condition too.

#### Scenario: Tamper detected triggers an alert

- GIVEN the hash-chain verification job runs against a tenant's `audit_logs`
- WHEN a row's recomputed hash does not match its stored `row_hash` (or a row is missing from the sequence)
- THEN the system MUST raise an alert distinguishable from normal operation — it MUST NOT fail silently or only log at debug level

#### Scenario: Verification job stopping is itself detected

- GIVEN the verification job is expected to run on a schedule
- WHEN it fails to execute (crash, misconfiguration, deployment gap) for longer than the expected interval
- THEN a dead-man's switch MUST detect the missed run and alert independently of the job itself
