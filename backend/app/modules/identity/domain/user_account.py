"""`UserAccount` (design.md §17.3): the identity module's own projection of
a `users` row joined with its (optional) `user_credentials` row -- the shape
`Login`/`RefreshToken`/`ConfirmAccountLink` need to resolve authn -> authz
and to mint a `TenantContext`. Distinct from any future `tenancy`-module
representation of a user; this one carries only the fields authn resolution
needs (design.md §2.4: business modules never share a domain type across
the module boundary, each keeps its own projection)."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class UserAccount:
    id: str
    tenant_id: str
    site_id: str
    role: str
    status: str
    email: str
    auth_subject: str | None
    email_verified_at: datetime | None

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def is_linked_to_federated_provider(self) -> bool:
        return self.auth_subject is not None
