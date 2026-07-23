"""`CreateShift` use case (design.md §5.3/§6, tasks.md task 8.2):
`authorize(ctx, action)` first, confirm the target staff member exists and is
currently assignable (`StaffPolicy.is_assignable` -- design.md §6/spec
`staff-registry` "Deactivated staff cannot be scheduled"), then create the
shift and audit. The DB's `EXCLUDE USING gist` (design.md §4.4) remains the
concurrency-safe floor for overlap -- see `PostgresShiftRepository`."""

from datetime import datetime

from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.governance.rbac.application.use_cases.authorize_action import AuthorizeAction
from app.modules.staff.application.ports.driven.shift_repository import ShiftRepositoryPort
from app.modules.staff.application.ports.driven.staff_repository import StaffRepositoryPort
from app.modules.staff.domain.errors import StaffMemberNotActiveError, StaffMemberNotFoundError
from app.modules.staff.domain.shift import Shift
from app.modules.staff.domain.staff_policy import StaffPolicy
from app.shared_kernel.tenant_context import TenantContext

_ACTION = "shift:create"


class CreateShift:
    def __init__(
        self,
        authorize: AuthorizeAction,
        staff_repository: StaffRepositoryPort,
        shift_repository: ShiftRepositoryPort,
        audit_log: AuditLogPort,
    ) -> None:
        self._authorize = authorize
        self._staff_repository = staff_repository
        self._shift_repository = shift_repository
        self._audit_log = audit_log

    async def execute(
        self, ctx: TenantContext, *, site_id: str, staff_member_id: str, starts_at: datetime, ends_at: datetime
    ) -> Shift:
        await self._authorize.execute(ctx, action=_ACTION)

        staff = await self._staff_repository.get_staff_member(ctx.tenant_id, staff_member_id)
        if staff is None:
            raise StaffMemberNotFoundError(staff_member_id)
        if not StaffPolicy.is_assignable(staff):
            raise StaffMemberNotActiveError(staff_member_id)

        shift = await self._shift_repository.create_shift(
            ctx.tenant_id, site_id=site_id, staff_member_id=staff_member_id, starts_at=starts_at, ends_at=ends_at
        )

        await self._audit_log.record(
            AuditEntry(
                tenant_id=ctx.tenant_id,
                site_id=site_id,
                actor_id=ctx.actor_id,
                actor_type=AuditActorType.USER,
                action=AuditAction.SHIFT_CREATE,
                object_type="shift",
                object_id=shift.id,
                payload={"staff_member_id": staff_member_id},
            )
        )
        return shift
