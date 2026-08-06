from datetime import datetime

from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.governance.rbac.application.use_cases.authorize_action import AuthorizeAction
from app.modules.staff.application.ports.driven.shift_repository import ShiftRepositoryPort
from app.modules.staff.domain.errors import ShiftNotFoundError
from app.modules.staff.domain.shift import Shift
from app.shared_kernel.tenant_context import TenantContext

_ACTION = "shift:edit"


class EditShift:
    def __init__(self, authorize: AuthorizeAction, shift_repository: ShiftRepositoryPort, audit_log: AuditLogPort) -> None:
        self._authorize = authorize
        self._shift_repository = shift_repository
        self._audit_log = audit_log

    async def execute(self, ctx: TenantContext, *, shift_id: str, starts_at: datetime, ends_at: datetime) -> Shift:
        await self._authorize.execute(ctx, action=_ACTION)

        existing = await self._shift_repository.get_shift(ctx.tenant_id, shift_id)
        if existing is None:
            raise ShiftNotFoundError(shift_id)

        edited = await self._shift_repository.edit_shift(ctx.tenant_id, shift_id, starts_at=starts_at, ends_at=ends_at)

        await self._audit_log.record(
            AuditEntry(
                tenant_id=ctx.tenant_id,
                site_id=edited.site_id,
                actor_id=ctx.actor_id,
                actor_type=AuditActorType.USER,
                action=AuditAction.SHIFT_EDIT,
                object_type="shift",
                object_id=edited.id,
                payload={"staff_member_id": edited.staff_member_id},
            )
        )
        return edited
