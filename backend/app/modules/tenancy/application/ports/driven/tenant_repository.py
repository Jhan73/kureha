"""`TenantRepositoryPort` (design.md §4.1): `tenants` access for the tenancy
module's lookup use case(s). Implemented in MVP by `PostgresTenantRepository`
(adapters/outbound/postgres/tenant_repository.py)."""

from typing import Protocol

from app.modules.tenancy.domain.tenant import Tenant


class TenantRepositoryPort(Protocol):
    async def get_by_id(self, tenant_id: str) -> Tenant | None:
        """Global lookup by primary key -- `tenants` itself carries no
        `tenant_id` column to scope by (it IS the tenant), and has no RLS
        (migration 613f9ea3526f: "`tenants` does not get RLS ... design.md
        never gives it a self-referential policy"). Returns `None` when no
        row matches; the caller (`GetTenant`) is responsible for turning that
        into `TenantNotFoundError`."""
        ...
