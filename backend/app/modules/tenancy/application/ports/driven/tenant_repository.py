from typing import Protocol

from app.modules.tenancy.domain.tenant import Tenant


class TenantRepositoryPort(Protocol):
    async def get_by_id(self, tenant_id: str) -> Tenant | None:
        """Global PK lookup; `tenants` has no RLS. None if missing."""
        ...
