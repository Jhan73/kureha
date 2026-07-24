"""Scheduling web-form router (tasks.md task 10.1): `POST
/appointments/schedule`, `POST /appointments/{id}/reschedule`, `POST
/appointments/{id}/cancel`, `POST /appointments/{id}/reminder`.

Every route runs BEHIND `AccessControlMiddleware` -- uses the request's
already-open, RLS-scoped `request.state.db_conn` and the resolved
`TenantContext`. RBAC is enforced INSIDE each use case's own
`AuthorizeAction.execute()` call (design.md §5.3: "every mutating use case
... starts by calling this") -- this router never re-checks it, matching
`ConnectPatientCalendar`'s own precedent of authorizing inside the use
case, not the router."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from app.composition_root import (
    build_cancel_appointment,
    build_reschedule_appointment,
    build_schedule_appointment,
    build_send_reminder,
)
from app.modules.scheduling.domain.appointment import Appointment
from app.platform.inbound.api.access_control.dependencies import get_db_conn, get_tenant_context
from app.shared_kernel.tenant_context import TenantContext

router = APIRouter(prefix="/appointments", tags=["appointments"])


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


@router.post("/schedule", response_model=AppointmentResponse, status_code=201)
async def schedule(
    payload: ScheduleAppointmentRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> AppointmentResponse:
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
    use_case = build_cancel_appointment(conn)
    appointment = await use_case.execute(ctx, appointment_id=appointment_id)
    return _to_response(appointment)


@router.post("/{appointment_id}/reminder", response_model=ReminderResponse)
async def send_reminder(
    appointment_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> ReminderResponse:
    use_case = build_send_reminder(conn)
    delivered = await use_case.execute(ctx, appointment_id=appointment_id)
    return ReminderResponse(delivered=delivered)
