"""`GetTenant` use case (design.md §4.1/§3.1, tasks.md task 6.1): the tenancy
lookup other modules consume -- takes a bare `tenant_id` (not a
`TenantContext`), because resolving the tenant is often a precondition to
having one in the first place (e.g. `Login`'s pre-auth flow needs to confirm
the tenant exists and is active before minting anything). No `authorize()`
gate: reading your own tenant's basic record is not an RBAC-gated action --
it is what makes the rest of authorization possible."""

from app.modules.tenancy.application.ports.driven.tenant_repository import TenantRepositoryPort
from app.modules.tenancy.domain.errors import TenantNotFoundError, TenantSuspendedError
from app.modules.tenancy.domain.tenant import Tenant
from app.modules.tenancy.domain.tenant_policy import TenantPolicy


class GetTenant:
    def __init__(self, tenant_repository: TenantRepositoryPort) -> None:
        self._tenant_repository = tenant_repository

    async def execute(self, tenant_id: str) -> Tenant:
        tenant = await self._tenant_repository.get_by_id(tenant_id)
        if tenant is None:
            raise TenantNotFoundError()
        if not TenantPolicy.is_usable(tenant):
            raise TenantSuspendedError()
        return tenant
