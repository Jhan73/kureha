"""`AuthorizationCodeExchange`: the result of exchanging an OAuth2
authorization `code` for a refresh token + the authorized Google account's
email (design.md §7.3, tasks.md task 10.1). Added alongside
`GoogleCalendarAdapter.exchange_authorization_code` -- the first call site in
this codebase that performs the `grant_type=authorization_code` leg of the
flow (every other Google API call this adapter makes starts from an
ALREADY-issued refresh token, see `google_calendar_adapter.py`'s own
docstring).

Transient, like `CalendarCredential` -- the plaintext `refresh_token` this
carries MUST NEVER be logged, audited, or persisted anywhere outside
`CredentialVaultPort`'s own encrypted storage (same contract
`CalendarCredential`'s docstring already establishes)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthorizationCodeExchange:
    refresh_token: str
    google_email: str
    scope: str
