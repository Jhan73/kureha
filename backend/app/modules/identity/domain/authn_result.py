"""`AuthnResult` (design.md §17.1): the output of `AuthPort.verify_password`/
`verify_federated` -- authn-only. Proves *who* the IdP thinks the caller is
(a stable subject + a verified-or-not email); it carries no `tenant_id`,
`site_id`, or `role` -- Kureha resolves those separately by mapping
`subject`/`email` to a `users` row (design.md §17.3, `UserDirectoryPort`)."""

from dataclasses import dataclass
from typing import Literal

AuthProvider = Literal["password", "google"]


@dataclass(frozen=True, slots=True)
class AuthnResult:
    subject: str
    email: str
    email_verified: bool
    provider: AuthProvider
