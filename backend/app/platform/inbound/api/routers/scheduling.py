from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from app.composition_root import (
    build_authorize_action,
    build_cancel_appointment,
    build_check_consent,
    build_reschedule_appointment,
    build_schedule_appointment,
    build_scheduling_repository,
    build_send_reminder,
)
from app.modules.governance.consent.domain.consent_policy import ConsentCheckResult
from app.modules.governance.consent.domain.errors import ConsentNotCurrentError
from app.modules.scheduling.domain.appointment import Appointment
from app.modules.scheduling.domain.errors import AppointmentNotFoundError
from app.platform.inbound.api.access_control.dependencies import get_db_conn, get_tenant_context
from app.shared_kernel.tenant_context import TenantContext

router = APIRouter(prefix="/appointments", tags=["appointments"])

# Must stay in sync with each use case's private `_ACTION` constant.
_SCHEDULE_ACTION = "appointment:create"
_RESCHEDULE_ACTION = "appointment:reschedule"
_CANCEL_ACTION = "appointment:cancel"
_REMINDER_ACTION = "appointment:view"  # no dedicated appointment:reminder action key


class ScheduleAppointmentRequest(BaseModel):
    patient_id: str
    professional_id: str
    site_id: str
    availability_id: str


class RescheduleAppointmentRequest(BaseModel):
    new_availability_id: str


class AppointmentResponse(BaseModel):
    id: str
    tenant_id: str
    site_id: str
    patient_id: str
    professional_id: str
    starts_at: datetime
    ends_at: datetime
    status: str


class ReminderResponse(BaseModel):
    delivered: bool


def _to_response(appointment: Appointment) -> AppointmentResponse:
    return AppointmentResponse(
        id=appointment.id,
        tenant_id=appointment.tenant_id,
        site_id=appointment.site_id,
        patient_id=appointment.patient_id,
        professional_id=appointment.professional_id,
        starts_at=appointment.starts_at,
        ends_at=appointment.ends_at,
        status=appointment.status.value,
    )


async def _require_authorized(conn: AsyncConnection, ctx: TenantContext, *, action: str) -> None:
    """Router-level RBAC before lookup/consent (avoids existence oracle; RBAC before consent)."""
    await build_authorize_action(conn).execute(ctx, action=action)


async def _resolve_patient_id(conn: AsyncConnection, ctx: TenantContext, appointment_id: str) -> str:
    """Authoritative patient_id from the appointment row (never trust a client-supplied value)."""
    appointment = await build_scheduling_repository(conn).get_appointment(ctx.tenant_id, appointment_id)
    if appointment is None:
        raise AppointmentNotFoundError(appointment_id)
    return appointment.patient_id


async def _require_current_consent(conn: AsyncConnection, ctx: TenantContext, patient_id: str) -> None:
    """Deny unless ConsentCheckResult.CURRENT (same gate as chat consent_gate)."""
    result = await build_check_consent(conn).execute(ctx, patient_id=patient_id)
    if result is not ConsentCheckResult.CURRENT:
        raise ConsentNotCurrentError(patient_id)


@router.post("/schedule", response_model=AppointmentResponse, status_code=201)
async def schedule(
    payload: ScheduleAppointmentRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> AppointmentResponse:
    await _require_authorized(conn, ctx, action=_SCHEDULE_ACTION)
    await _require_current_consent(conn, ctx, payload.patient_id)
    use_case = build_schedule_appointment(conn)
    appointment = await use_case.execute(
        ctx,
        patient_id=payload.patient_id,
        professional_id=payload.professional_id,
        site_id=payload.site_id,
        availability_id=payload.availability_id,
    )
    return _to_response(appointment)


@router.post("/{appointment_id}/reschedule", response_model=AppointmentResponse)
async def reschedule(
    appointment_id: str,
    payload: RescheduleAppointmentRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> AppointmentResponse:
    await _require_authorized(conn, ctx, action=_RESCHEDULE_ACTION)
    patient_id = await _resolve_patient_id(conn, ctx, appointment_id)
    await _require_current_consent(conn, ctx, patient_id)
    use_case = build_reschedule_appointment(conn)
    appointment = await use_case.execute(
        ctx, appointment_id=appointment_id, new_availability_id=payload.new_availability_id
    )
    return _to_response(appointment)


@router.post("/{appointment_id}/cancel", response_model=AppointmentResponse)
async def cancel(
    appointment_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> AppointmentResponse:
    await _require_authorized(conn, ctx, action=_CANCEL_ACTION)
    patient_id = await _resolve_patient_id(conn, ctx, appointment_id)
    await _require_current_consent(conn, ctx, patient_id)
    use_case = build_cancel_appointment(conn)
    appointment = await use_case.execute(ctx, appointment_id=appointment_id)
    return _to_response(appointment)


@router.post("/{appointment_id}/reminder", response_model=ReminderResponse)
async def send_reminder(
    appointment_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> ReminderResponse:
    await _require_authorized(conn, ctx, action=_REMINDER_ACTION)
    patient_id = await _resolve_patient_id(conn, ctx, appointment_id)
    await _require_current_consent(conn, ctx, patient_id)
    use_case = build_send_reminder(conn)
    delivered = await use_case.execute(ctx, appointment_id=appointment_id)
    return ReminderResponse(delivered=delivered)
