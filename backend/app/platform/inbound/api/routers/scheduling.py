"""Scheduling web-form router (tasks.md task 10.1): `POST
/appointments/schedule`, `POST /appointments/{id}/reschedule`, `POST
/appointments/{id}/cancel`, `POST /appointments/{id}/reminder`.

Every route runs BEHIND `AccessControlMiddleware` -- uses the request's
already-open, RLS-scoped `request.state.db_conn` and the resolved
`TenantContext`. RBAC is enforced INSIDE each use case's own
`AuthorizeAction.execute()` call (design.md §5.3: "every mutating use case
... starts by calling this") -- this router ALSO re-checks it explicitly,
see `_require_authorized` below, before the (also new) consent gate.

**Gap closure (sdd-verify `verify-report` #414, CRITICAL): consent gate for
the web-form channel.** Spec `patient-self-service-portal` -> "Consent Gate
Enforced in Portal" (MUST) requires every data-touching form submission to
verify the patient has active consent (`versioned-consent`) before
proceeding, and to block otherwise. This was unimplemented full-stack for
this router since it was first built (task 10.1, PR 10) -- `ScheduleAppointment`
`schedule_appointment.py`'s own docstring always said "consent is checked
upstream by the caller", but no caller ever existed here. The chat channel's
equivalent, `platform/inbound/graph/nodes/consent_gate.py` (task 11.2, PR
11), DID get built and wire `CheckConsent` correctly -- this router never
did, and the gap went uncaught until this Phase 14 verify pass (see that
pass's own note: PR10's original verify did not check for this requirement
at all). This closure wires the SAME `CheckConsent` use case
(`governance/consent`, design.md §11) here, following `consent_gate.py`'s
own established pattern (deny-by-default, `ConsentCheckResult.CURRENT` is
the only pass state) for all 4 mutating actions (schedule, reschedule,
cancel, reminder) -- `consent_gate.py`'s own docstring lists exactly these
4 as the patient-data-touching intents.

**Order per route: `_require_authorized` (RBAC) -> resolve `patient_id` ->
consent check -> the actual use case.** Deliberately RBAC-before-consent,
NOT the chat graph's edge order (`consent_gate` before `resolve_toolset`/
RBAC, design.md §8.3) -- this router's OWN pre-existing, already-verified
test (`test_schedule_appointment_is_denied_for_a_patient_actor_via_the_real_rbac_chain`)
established RBAC-denial-takes-priority as the expected/correct behavior for
this channel, and reversing that order for `reschedule`/`cancel`/`reminder`
would introduce an appointment-existence oracle (an unauthorized actor
could distinguish "404 not found" from "403 forbidden" before ever being
authorized to know the appointment exists at all) -- `_require_authorized`
therefore ALWAYS runs first, exactly mirroring each use case's own internal
`authorize() -> get_appointment()` order, so a 404-vs-403 leak is never
introduced by this gate. This does mean `AuthorizeAction.execute()` runs
TWICE per request (once here, once again inside the use case itself) --
intentional, minor, side-effect-free duplication, flagged not silently
free, kept because the use cases are NOT changed by this closure (task's
own scope boundary: the router/caller layer, not the business modules).

`patient_id` resolution: `schedule` carries it directly on the request body
(trusted the same way `ScheduleAppointment.execute` already trusts it
today -- unchanged by this closure). `reschedule`/`cancel`/`reminder` do
NOT carry `patient_id` as a request field at all (only `appointment_id`) --
trusting an ATTACKER-SUPPLIED `patient_id` field for the consent check
while operating on a DIFFERENT patient's appointment would itself be a
bypass, so this resolves the authoritative `patient_id` from the existing
appointment row instead (`build_scheduling_repository(conn).get_appointment`,
the SAME RLS-scoped connection, same read every one of these use cases
already performs internally)."""

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

# Mirrors each use case's own private `_ACTION` module constant
# (schedule_appointment.py/reschedule_appointment.py/cancel_appointment.py/
# send_reminder.py) -- duplicated here (not imported, those are private)
# because `_require_authorized` runs its OWN explicit `AuthorizeAction`
# check ahead of the use case's internal one (see module docstring for
# why). MUST stay in sync with each use case's `_ACTION` value.
_SCHEDULE_ACTION = "appointment:create"
_RESCHEDULE_ACTION = "appointment:reschedule"
_CANCEL_ACTION = "appointment:cancel"
_REMINDER_ACTION = "appointment:view"  # SendReminder's own docstring: no dedicated appointment:reminder action key


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
    """Explicit, router-level RBAC check -- runs BEFORE both the
    appointment lookup (`_resolve_patient_id`) and the consent gate
    (`_require_current_consent`), so this router never introduces an
    appointment-existence oracle and RBAC denials keep taking priority over
    consent denials (see module docstring). The target use case's own
    internal `AuthorizeAction.execute()` call still runs too -- redundant
    but harmless, deliberately not removed (out of this closure's scope)."""
    await build_authorize_action(conn).execute(ctx, action=action)


async def _resolve_patient_id(conn: AsyncConnection, ctx: TenantContext, appointment_id: str) -> str:
    """Resolves the authoritative `patient_id` for an EXISTING appointment
    (`reschedule`/`cancel`/`reminder` never carry `patient_id` as a request
    field -- see module docstring for why this must not simply trust a
    client-supplied value). Raises the SAME `AppointmentNotFoundError` the
    target use case would raise for a missing/RLS-invisible row, so the 404
    contract for that case is unchanged by this closure."""
    appointment = await build_scheduling_repository(conn).get_appointment(ctx.tenant_id, appointment_id)
    if appointment is None:
        raise AppointmentNotFoundError(appointment_id)
    return appointment.patient_id


async def _require_current_consent(conn: AsyncConnection, ctx: TenantContext, patient_id: str) -> None:
    """The consent gate itself (verify-report #414 closure): mirrors
    `platform/inbound/graph/nodes/consent_gate.py`'s already-established
    pattern for the chat channel -- deny-by-default, only
    `ConsentCheckResult.CURRENT` passes."""
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
