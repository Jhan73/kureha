# Google Calendar Sync Specification (google-calendar-sync)

## Purpose

`CalendarSyncPort` mirrors appointment create/reschedule/cancel into the patient's Google Calendar via OAuth2, tied to the patient's registered email. This is a **best-effort, non-transactional side effect**: Kureha's own confirmation is the source of truth and MUST NOT be blocked or rolled back by a calendar sync failure.

## Requirements

### Requirement: Best-Effort Non-Blocking Sync

The appointment use case MUST commit the Kureha-side appointment (with its audit entry) in its own transaction before attempting `CalendarSyncPort`. A `CalendarSyncPort` failure MUST NOT roll back or block the already-confirmed appointment.

#### Scenario: Google API failure mid-sync

- GIVEN an appointment is created and committed in Kureha
- WHEN the subsequent call to `CalendarSyncPort` fails (timeout, auth error, quota, etc.)
- THEN the Kureha appointment remains confirmed and visible to the patient
- AND the sync status is recorded as `failed`, with the failure audited

#### Scenario: Google API succeeds

- GIVEN an appointment is created and committed in Kureha
- WHEN `CalendarSyncPort` succeeds
- THEN the sync status is recorded as `ok` and the resulting Google event reference is stored

### Requirement: Explicit Sync Status Tracking

Every calendar-sync attempt MUST persist a status among `pending`, `ok`, or `failed`, associated with the appointment and patient, and be independently auditable.

#### Scenario: Failure recorded and retried

- GIVEN a sync attempt failed and status is `failed`
- WHEN a retry (per policy) later succeeds
- THEN the status MUST transition to `ok` and both the failure and the eventual success MUST be visible in the audit trail

### Requirement: OAuth2 Scope and Token Security

The system MUST request the minimal OAuth2 scope required for calendar event management (no broader Google account access). The system MUST store refresh tokens encrypted at rest and MUST NOT persist plaintext tokens. The system MUST support token revocation.

#### Scenario: Patient revokes Google access

- GIVEN a patient revokes Kureha's Google Calendar access from their Google account
- WHEN a subsequent sync attempt is made
- THEN it MUST fail with status `failed` and reason `revoked`
- AND MUST NOT be retried indefinitely, and MUST NOT surface as a blocking error to the patient's Kureha appointment flow

#### Scenario: Token storage requirement

- GIVEN a refresh token is issued during the OAuth2 flow
- WHEN it is persisted
- THEN it MUST be stored in encrypted form — inspecting the storage layer alone MUST NOT reveal the plaintext token

### Requirement: Per-Patient OAuth Using Registered Email

The OAuth2 flow MUST be tied to the patient's own registered account email. The system MUST NOT sync appointments to a Google account not authorized by that same patient.

#### Scenario: Authorized account mismatch

- GIVEN a patient's registered email is `a@example.com`
- WHEN they complete Google OAuth using a different Google account `b@example.com`
- THEN the system MUST flag the mismatch and MUST NOT silently sync under the mismatched account without explicit patient confirmation

### Requirement: Idempotent Sync Retries

Retried `CalendarSyncPort` attempts for the same appointment MUST NOT create a duplicate Google Calendar event. The system MUST derive a deterministic idempotency key (or event id) from `appointment_id` and use it to upsert rather than blindly insert on each attempt.

#### Scenario: Retry after transient failure does not duplicate the event

- GIVEN a sync attempt for an appointment failed after a partial upstream effect (e.g. timeout after Google accepted the insert)
- WHEN the retry job attempts the sync again for the same appointment
- THEN the system MUST use the appointment's idempotency key to upsert the existing event, not insert a second one
- AND `calendar_sync` MUST end with exactly one `google_event_id` for that appointment

#### Scenario: First successful attempt establishes the key

- GIVEN a new appointment has never been synced
- WHEN the first sync attempt succeeds
- THEN the deterministic idempotency key derived from `appointment_id` MUST be associated with the resulting `google_event_id` for all future retries of that appointment