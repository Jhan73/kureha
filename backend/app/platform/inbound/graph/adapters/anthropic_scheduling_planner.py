from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.platform.inbound.graph.ports.scheduling_planner import SchedulingPlan
from app.shared_kernel.tenant_context import TenantContext

_ACTION_BY_INTENT: dict[str, str] = {
    "schedule": "appointment:create",
    "reschedule": "appointment:reschedule",
    "cancel": "appointment:cancel",
}

# `use_case.execute(ctx, **kwargs)`'s own required-keyword shape per action
# (verified by reading `ScheduleAppointment`/`RescheduleAppointment`/
# `CancelAppointment.execute` directly, not guessed) -- restricts `kwargs`
# to ONLY the fields the target use case actually accepts, so an extracted
# field irrelevant to this action (e.g. `patient_id` for a cancel) never
# leaks into the dispatched call.
_KWARGS_FIELDS_BY_ACTION: dict[str, tuple[str, ...]] = {
    "appointment:create": ("patient_id", "professional_id", "site_id", "availability_id"),
    "appointment:reschedule": ("appointment_id", "new_availability_id"),
    "appointment:cancel": ("appointment_id",),
}

_SYSTEM_PROMPT = (
    "You are the scheduling planner for Tony, a Peruvian clinic operations chat "
    "assistant. Given the user's message, extract whatever concrete details are "
    "explicitly present (patient/professional/site/availability/appointment "
    "identifiers ONLY if the user literally states one -- never invent or guess "
    "one) and write a short, human-readable `summary` of the intended action in "
    "the user's own language (this text is shown to the user as a confirmation "
    "prompt, so it must be accurate and specific to what they asked). If the "
    "message implies cancelling MULTIPLE appointments, list every appointment id "
    "you can identify in `appointment_ids`. If the message implies moving an "
    "appointment to a DIFFERENT professional than the one currently assigned, set "
    "`requested_professional_id` (who the user asked for) and "
    "`target_professional_id` (who the new slot would actually assign, if known)."
)


class _SchedulingExtraction(BaseModel):
    patient_id: str | None = None
    professional_id: str | None = None
    site_id: str | None = None
    availability_id: str | None = None
    appointment_id: str | None = None
    new_availability_id: str | None = None
    appointment_ids: list[str] | None = None
    requested_professional_id: str | None = None
    target_professional_id: str | None = None
    summary: str = ""


class AnthropicSchedulingPlanner:
    """Duck-types `SchedulingPlannerPort`."""

    def __init__(self, llm) -> None:
        self._structured = llm.with_structured_output(_SchedulingExtraction)

    async def plan(self, ctx: TenantContext, *, intent: str, message: str) -> SchedulingPlan:
        action = _ACTION_BY_INTENT.get(intent)
        if action is None:
            raise ValueError(f"AnthropicSchedulingPlanner.plan called with unsupported intent {intent!r}")

        # No local catch — planner failures propagate to the central error handler.
        verdict = await self._structured.ainvoke(
            [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=message)]
        )

        fields = _KWARGS_FIELDS_BY_ACTION[action]
        kwargs = {name: value for name in fields if (value := getattr(verdict, name)) is not None}

        return SchedulingPlan(
            action=action,
            kwargs=kwargs,
            summary=verdict.summary,
            appointment_ids=verdict.appointment_ids,
            requested_professional_id=verdict.requested_professional_id,
            target_professional_id=verdict.target_professional_id,
        )
