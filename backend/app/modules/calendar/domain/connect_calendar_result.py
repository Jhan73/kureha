"""Outcome types for `ConnectPatientCalendar` (design.md §7.3, tasks.md task
9.4), mirroring `identity.domain.login_result`'s `LoginResult |
AccountLinkRequired` shape: two distinct, non-error outcomes, both RETURNED
(never raised) -- an email mismatch is an expected branch of this flow, not
a failure.

- `CalendarConnected`: the Google account's email matched the patient's own
  registered email (or no registered email was on file to compare against);
  the refresh token was encrypted and persisted.
- `CalendarEmailMismatch`: spec `google-calendar-sync` -> "Authorized account
  mismatch" -- the authorized Google account's email does NOT match the
  patient's registered email. Nothing is persisted; the caller (a future
  Phase 10 endpoint) is responsible for obtaining the patient's EXPLICIT
  confirmation before calling this use case again in a way that overrides
  the check (not built in this phase -- no such override path exists yet,
  matching the spec's "MUST NOT silently sync ... without explicit patient
  confirmation").
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CalendarConnected:
    credential_id: str


@dataclass(frozen=True, slots=True)
class CalendarEmailMismatch:
    registered_email: str
    google_email: str
