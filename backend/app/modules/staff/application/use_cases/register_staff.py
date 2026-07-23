"""`RegisterStaff` use case (design.md §5.3/§6, tasks.md task 8.2):
`authorize(ctx, action)` first, then create the operational registry row and
audit -- all in the caller's already-open transaction, same "same
transaction" contract every other business-module use case follows (ADR-3).

No HR fields accepted here by construction -- `site_id`/`name`/
`operational_role`/`user_id`/`professional_id` is the entire surface, matching
spec `staff-registry`'s "Out-of-HR-Scope Boundary" (no payroll/contracts/
performance-evaluation)."""

from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.governance.rbac.application.use_cases.authorize_action import AuthorizeAction
from app.modules.staff.application.ports.driven.staff_repository import StaffRepositoryPort
from app.modules.staff.domain.staff_member import OperationalRole, StaffMember
from app.shared_kernel.tenant_context import TenantContext

_ACTION = "staff:register"


class RegisterStaff:
    def __init__(
        self,
        authorize: AuthorizeAction,
        staff_repository: StaffRepositoryPort,
        audit_log: AuditLogPort,
    ) -> None:
        self._authorize = authorize
        self._staff_repository = staff_repository
        self._audit_log = audit_log

    async def execute(
        self,
        ctx: TenantContext,
        *,
        site_id: str,
        name: str,
        operational_role: OperationalRole,
        user_id: str | None = None,
        professional_id: str | None = None,
    ) -> StaffMember:
        await self._authorize.execute(ctx, action=_ACTION)

        staff = await self._staff_repository.create_staff_member(
            ctx.tenant_id,
            site_id=site_id,
            name=name,
            operational_role=operational_role,
            user_id=user_id,
            professional_id=professional_id,
        )

        await self._audit_log.record(
            AuditEntry(
                tenant_id=ctx.tenant_id,
                site_id=site_id,
                actor_id=ctx.actor_id,
                actor_type=AuditActorType.USER,
                action=AuditAction.STAFF_REGISTER,
                object_type="staff_member",
                object_id=staff.id,
                payload={"name": name, "operational_role": operational_role.value},
            )
        )
        return staff
