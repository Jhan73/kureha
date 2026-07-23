"""`ScheduleAppointment` use case (design.md §5.3/§9, tasks.md task 7.3):
`authorize(ctx, action)` first, then reserve the requested slot, create the
appointment, and audit -- all in the caller's already-open transaction
(design.md §9: "Formulario web ... SI por AuthorizeAction + consent + audit";
ADR-3: audit in the same transaction as the action). Consent is checked
upstream by the caller (governance/consent's `CheckConsent`, design.md §11)
-- not repeated here, mirroring how `AuthorizeAction` itself stays a single
concern.

Does NOT invoke `RiskPolicy` -- HITL routing on `risk_level` is the future
`scheduling_agent`/`rbac_gate` graph nodes' job (tasks.md Phase 11), applied
BEFORE this use case runs. By the time `ScheduleAppointment.execute` is
called, any required approval has already happened.

Checks `StaffStatusPort.is_assignable` right after `authorize()` and before
touching either repository (tasks.md task 8.4, spec `staff-registry` ->
"Deactivated staff cannot be scheduled") -- fails fast on the cheapest
precondition, and guarantees no availability/appointment mutation is ever
attempted for a professional the staff module has deactivated."""

from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.governance.rbac.application.use_cases.authorize_action import AuthorizeAction
from app.modules.scheduling.application.ports.driven.availability_repository import AvailabilityRepositoryPort
from app.modules.scheduling.application.ports.driven.scheduling_repository import SchedulingRepositoryPort
from app.modules.scheduling.application.ports.driven.staff_status_port import StaffStatusPort
from app.modules.scheduling.domain.appointment import Appointment
from app.modules.scheduling.domain.errors import (
    AvailabilitySlotNotFoundError,
    SlotUnavailableError,
    StaffNotAssignableError,
)
from app.shared_kernel.tenant_context import TenantContext

_ACTION = "appointment:create"


class ScheduleAppointment:
    def __init__(
        self,
        authorize: AuthorizeAction,
        availability_repository: AvailabilityRepositoryPort,
        scheduling_repository: SchedulingRepositoryPort,
        audit_log: AuditLogPort,
        staff_status: StaffStatusPort,
    ) -> None:
        self._authorize = authorize
        self._availability_repository = availability_repository
        self._scheduling_repository = scheduling_repository
        self._audit_log = audit_log
        self._staff_status = staff_status

    async def execute(
        self,
        ctx: TenantContext,
        *,
        patient_id: str,
        professional_id: str,
        site_id: str,
        availability_id: str,
    ) -> Appointment:
        await self._authorize.execute(ctx, action=_ACTION)

        if not await self._staff_status.is_assignable(ctx.tenant_id, professional_id):
            raise StaffNotAssignableError(f"Professional {professional_id} is not assignable")

        slot = await self._availability_repository.get_slot(ctx.tenant_id, availability_id)
        if slot is None:
            raise AvailabilitySlotNotFoundError(availability_id)
        if not slot.is_available:
            raise SlotUnavailableError(f"slot {availability_id} is not available")

        reserved = await self._availability_repository.reserve_slot(ctx.tenant_id, availability_id)

        appointment = await self._scheduling_repository.create_appointment(
            ctx.tenant_id,
            site_id=site_id,
            patient_id=patient_id,
            professional_id=professional_id,
            availability_id=availability_id,
            starts_at=reserved.starts_at,
            ends_at=reserved.ends_at,
        )

        await self._audit_log.record(
            AuditEntry(
                tenant_id=ctx.tenant_id,
                site_id=site_id,
                actor_id=ctx.actor_id,
                actor_type=AuditActorType.USER,
                action=AuditAction.APPOINTMENT_CREATE,
                object_type="appointment",
                object_id=appointment.id,
                payload={"patient_id": patient_id, "professional_id": professional_id},
            )
        )
        return appointment
