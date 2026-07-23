"""`DeactivateStaff` use case (design.md §5.3/§6, tasks.md task 8.2):
`authorize(ctx, action)` first, load the existing staff member, deactivate
(a status flip -- `StaffRepositoryPort.deactivate_staff_member` never
deletes, design.md §6's "baja no borra historia"), and audit -- same "same
transaction" contract as `RegisterStaff` (ADR-3)."""

from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.governance.rbac.application.use_cases.authorize_action import AuthorizeAction
from app.modules.staff.application.ports.driven.staff_repository import StaffRepositoryPort
from app.modules.staff.domain.errors import StaffMemberNotFoundError
from app.modules.staff.domain.staff_member import StaffMember
from app.shared_kernel.tenant_context import TenantContext

_ACTION = "staff:deactivate"


class DeactivateStaff:
    def __init__(
        self,
        authorize: AuthorizeAction,
        staff_repository: StaffRepositoryPort,
        audit_log: AuditLogPort,
    ) -> None:
        self._authorize = authorize
        self._staff_repository = staff_repository
        self._audit_log = audit_log

    async def execute(self, ctx: TenantContext, *, staff_member_id: str) -> StaffMember:
        await self._authorize.execute(ctx, action=_ACTION)

        existing = await self._staff_repository.get_staff_member(ctx.tenant_id, staff_member_id)
        if existing is None:
            raise StaffMemberNotFoundError(staff_member_id)

        deactivated = await self._staff_repository.deactivate_staff_member(ctx.tenant_id, staff_member_id)

        await self._audit_log.record(
            AuditEntry(
                tenant_id=ctx.tenant_id,
                site_id=deactivated.site_id,
                actor_id=ctx.actor_id,
                actor_type=AuditActorType.USER,
                action=AuditAction.STAFF_DEACTIVATE,
                object_type="staff_member",
                object_id=deactivated.id,
            )
        )
        return deactivated
