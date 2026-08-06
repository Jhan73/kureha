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
