"""`AnthropicSchedulingPlanner`: the real `SchedulingPlannerPort` adapter
`scheduling_agent` consumes (tasks.md task 12.7, design.md §8.4 point 1/
§8.10). Reasoner tier -- design.md §8.10: "Planificacion multi-paso: entiende
disponibilidad, restricciones, genera `proposed_action` estructurada."
Constructor-injected `ChatAnthropic`, built ONLY via `platform/inbound/graph/
adapters/llm.py`'s `build_chat_model("reasoner")` at the composition root --
never inline here.

**`action` is derived from `intent` DETERMINISTICALLY, never guessed by the
model.** `scheduling_agent` only ever calls `plan()` with `intent` already
one of `"schedule"`/`"reschedule"`/`"cancel"` (`triage`'s own `Literal`-
constrained classification, upstream). A static `intent -> ActionKey` map
(`_ACTION_BY_INTENT`) resolves `action`; asking the LLM to re-derive
something already known would only add a NEW failure mode (a malformed/
invented action string) for zero benefit.

---

## THE ID-RESOLUTION GAP -- read this before touching this module

**Neither this adapter nor `AnthropicStaffPlanner`/`AnthropicReminderPlanner`
can invent a real database ID (`patient_id`, `professional_id`,
`availability_id`, `appointment_id`, `staff_member_id`, `shift_id`) out of
conversational text alone -- this is a genuine, UNRESOLVED architectural
gap in this codebase today, not something this batch invents a workaround
for.**

Confirmed by reading every layer this call passes through:

1. **`SchedulingPlannerPort.plan(ctx: TenantContext, *, intent, message)`**
   (`ports/scheduling_planner.py`) receives a bare `TenantContext`
   (`tenant_id`/`role`/`site_id`/`actor_id` only -- see that type's own
   docstring: "the four pieces of request-scoped identity RLS's GUCs and
   RBAC's precedence resolution both need"), never `RequestContext` (which
   DOES carry `patient_id`/`professional_id` for the caller's OWN identity,
   `state.py`'s own docstring) -- `scheduling_agent.py` converts via
   `state["request_ctx"].to_tenant_context()` before calling `plan()`, which
   drops `patient_id`/`professional_id` by construction. So even the
   patient's OWN id (self-service scheduling) never reaches this adapter
   through the port's current signature.
2. **No slot/availability lookup port exists anywhere in this codebase.**
   `AvailabilityRepositoryPort` (`modules/scheduling/application/ports/
   driven/availability_repository.py`) is a DRIVEN port only
   `ScheduleAppointment`/`RescheduleAppointment` (the use cases, not this
   graph layer) call, scoped to Postgres-backed use cases running AFTER
   RBAC/confirmation clear -- nothing in `platform/inbound/graph/` exposes an
   equivalent "look up an `availability_id` by natural-language date/
   professional" TOOL CALL this planner could invoke mid-plan. The same is
   true for a "find the appointment the user means by 'my Tuesday
   appointment'" lookup, or a "find the staff_member_id for 'Dr. Garcia'"
   lookup.
3. **This is why `web_form` (design.md §9's deterministic channel) is the
   only production-ready path for these actions today** -- it passes real
   IDs directly from a UI that already resolved them (a dropdown/calendar
   picker), never through free text an LLM has to interpret.

**What this adapter actually does, honestly, given the above:** extracts
whatever the model CAN determine from `message` alone -- a human-readable
`summary` (used verbatim as the `confirmation_gate` prompt text, this part
genuinely works) and, ONLY if the message happens to literally contain an
ID-shaped token (e.g. a UUID a future quick-reply UI might paste verbatim --
not something today's `patient_chat`/`staff_copilot` message text
realistically contains), the corresponding kwarg. **`plan.kwargs` only ever
contains keys the model actually extracted -- never a key set to `None`.**
This is a deliberate safety choice: `persist_and_audit`'s
`use_case.execute(ctx, **proposed_action.payload)` (tasks.md task 11.5) has
no `None`-handling of its own for e.g. `availability_id` -- passing `None`
through would either raise a confusing, deep SQL-layer error or (worse) get
silently coerced somewhere unexpected. Omitting the key instead makes a
missing required field surface as a CLEAN, loud `TypeError: execute()
missing N required keyword-only argument(s): ...` the moment `persist_and_
audit` calls the real use case -- propagated by that node's own
already-established "no try/except" contract straight to the central error
handler (`register_exception_handlers`, task 10.3), exactly like any other
use-case exception in this codebase. **Never a fabricated, plausible-looking
ID that could silently mutate the WRONG row.**

**Practical consequence, stated plainly for whoever reviews this:** as of
this batch, the conversational (`patient_chat`/`staff_copilot`) path for
`schedule`/`reschedule`/`cancel` will almost always reach `rbac_gate` and
`confirmation_gate` successfully (those only inspect `action`/
`is_mutating`, never `payload`), let the user AFFIRM a confirmation prompt,
and only THEN fail at `persist_and_audit` with a missing-kwarg `TypeError`
-- a real, poor UX gap, but a SAFE one (loud failure, no data corruption,
no wrong-patient mutation). Closing this for real needs either (a) a new
graph node/tool-call round trip that resolves natural-language references
to real IDs before `scheduling_agent` plans, or (b) `SchedulingPlannerPort`
gaining an explicit "needs more info" return shape `direct_respond`-style
clarification could route to -- NEITHER is invented here; both are flagged
as the natural next step for whoever picks this up (likely batch 3 or a
dedicated follow-up, since either option is itself graph-topology work, not
just another adapter)."""

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

        # Deliberately NO try/except here -- see this module's own docstring:
        # `scheduling_agent`'s only outgoing edge is unconditional
        # (`add_edge("scheduling_agent", "rbac_gate")`, `build_graph.py`),
        # there is no designed failure-routing edge to fall back to, so a
        # planner failure propagates to the central error handler exactly
        # like `persist_and_audit`'s own established posture.
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
