from app.modules.tenancy.domain.tenant import Tenant


class TenantPolicy:
    @staticmethod
    def is_usable(tenant: Tenant) -> bool:
        """Suspended tenants must not resolve a usable request context."""
        return tenant.is_active
