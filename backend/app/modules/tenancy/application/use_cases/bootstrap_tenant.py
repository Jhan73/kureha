from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.tenancy.application.ports.driven.rbac_seeder import RbacSeederPort
from app.modules.tenancy.application.ports.driven.tenant_provisioning_repository import (
    TenantProvisioningRepositoryPort,
)
from app.modules.tenancy.domain.bootstrap_policy import BootstrapPolicy
from app.modules.tenancy.domain.tenant_bootstrap import BootstrapTenantCommand, TenantBootstrapResult
from app.shared_kernel.id_generator import IdGeneratorPort

_RBAC_MATRIX_LABEL = "dev-placeholder"


class BootstrapTenant:
    def __init__(
        self,
        repository: TenantProvisioningRepositoryPort,
        rbac_seeder: RbacSeederPort,
        audit_log: AuditLogPort,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._repository = repository
        self._rbac_seeder = rbac_seeder
        self._audit_log = audit_log
        self._id_generator = id_generator

    async def execute(
        self, command: BootstrapTenantCommand, *, operator_key_id: str | None = None
    ) -> TenantBootstrapResult:
        BootstrapPolicy.validate_name(command.name)
        BootstrapPolicy.validate_admin_email(command.admin_email)
        site_name = BootstrapPolicy.resolve_site_name(command.name, command.site_name)

        tenant_id = command.tenant_id or self._id_generator.new_id()
        site_id = self._id_generator.new_id()
        admin_user_id = self._id_generator.new_id()

        await self._repository.provision(
            tenant_id=tenant_id,
            name=command.name,
            site_id=site_id,
            site_name=site_name,
            admin_user_id=admin_user_id,
            admin_email=command.admin_email,
        )

        await self._rbac_seeder.seed_for_tenant(tenant_id)

        await self._audit_log.record(
            AuditEntry(
                tenant_id=tenant_id,
                site_id=site_id,
                actor_type=AuditActorType.SYSTEM,
                action=AuditAction.TENANT_BOOTSTRAP,
                object_type="tenant",
                object_id=tenant_id,
                payload={
                    "operator_key_id": operator_key_id,
                    "admin_email": command.admin_email,
                    "site_name": site_name,
                    "rbac_matrix": _RBAC_MATRIX_LABEL,
                },
            )
        )

        return TenantBootstrapResult(
            tenant_id=tenant_id,
            site_id=site_id,
            admin_user_id=admin_user_id,
            admin_email=command.admin_email,
        )
