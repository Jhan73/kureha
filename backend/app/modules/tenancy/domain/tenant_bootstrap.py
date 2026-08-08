from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BootstrapTenantCommand:
    name: str
    admin_email: str
    tenant_id: str | None = None
    site_name: str | None = None


@dataclass(frozen=True, slots=True)
class TenantBootstrapResult:
    tenant_id: str
    site_id: str
    admin_user_id: str
    admin_email: str
