"""`TenantContext`: the value object almost every use case receives.

Pure value object -- no IO, no business logic (design.md §2.5). Carries the
four pieces of request-scoped identity that RLS's `SET LOCAL app.*` GUCs
(design.md §4.2) and RBAC's precedence resolution (§5.2) both need: which
tenant, which site, which role, and who the acting user is. Not to be
confused with `Tenant` (the persisted entity with the tenant's own config),
which lives in `app.modules.tenancy` -- `TenantContext` never touches
Postgres and every module may import it freely.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Immutable snapshot of the acting request's identity.

    - `tenant_id`: the clinic (tenant) the request is scoped to.
    - `site_id`: the site within the tenant, when the actor is site-bound
      (`None` for tenant-wide actors, e.g. some `admin` operations).
    - `role`: one of `patient`, `reception`, `professional`, `admin`
      (design.md §4.1's `users.role` CHECK constraint).
    - `actor_id`: the acting `users.id`, or `None` for anonymous/system
      contexts that never resolved to an authenticated `users` row.
    """

    tenant_id: str
    role: str
    site_id: str | None = None
    actor_id: str | None = None
