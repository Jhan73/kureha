"""Outcome types for `Login` (design.md §17.3/§17.4). Two distinct success
shapes, both returned (never raised) since neither is an error condition:

- `LoginResult`: authn resolved to exactly one `users` row and a fresh
  access+refresh pair was minted.
- `AccountLinkRequired`: a Google sign-in's verified email matches an
  EXISTING password-based account that has no federated subject linked yet
  -- spec `user-authentication` -> "Email Verification for Account Linking"
  requires explicit confirmation before linking, so no token is minted yet.
  The caller (a future Phase 10 endpoint) is responsible for obtaining that
  confirmation (e.g. re-authenticating with the existing password) before
  calling `ConfirmAccountLink`.
"""

from dataclasses import dataclass

from app.modules.identity.domain.user_account import UserAccount


@dataclass(frozen=True, slots=True)
class LoginResult:
    access_token: str
    refresh_token: str
    user: UserAccount


@dataclass(frozen=True, slots=True)
class AccountLinkRequired:
    existing_user_id: str
    email: str
    pending_subject: str
    email_verified: bool
