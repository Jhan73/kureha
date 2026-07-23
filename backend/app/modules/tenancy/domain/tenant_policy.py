"""`TenantPolicy` (design.md §3.1): pure rule -- no IO -- deciding whether a
resolved `Tenant` is usable for a request. Mirrors `SessionPolicy`/
`ConsentPolicy`'s split: the use case owns the lookup (`GetTenant`), this
owns the verdict, so the rule stays testable without a database."""

from app.modules.tenancy.domain.tenant import Tenant


class TenantPolicy:
    @staticmethod
    def is_usable(tenant: Tenant) -> bool:
        """A suspended tenant (design.md §4.1 `tenants.status`) must never
        resolve a usable request context -- every module that looks up a
        tenant (e.g. pre-auth resolution, the graph's `route_from_start`)
        gates on this before proceeding, the same "live status" pattern
        design.md §4.2 already applies to `users.status`/
        `staff_members.status`."""
        return tenant.is_active
