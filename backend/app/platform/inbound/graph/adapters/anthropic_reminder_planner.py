"""`AnthropicReminderPlanner`: the real `ReminderPlannerPort` adapter
`reminders_agent` consumes (tasks.md task 12.7, design.md §8.10: "Tarea
simple: generar texto de recordatorio parametrico"). Fast/small tier.
Constructor-injected `ChatAnthropic`, built ONLY via `platform/inbound/graph/
adapters/llm.py`'s `build_chat_model("fast")` at the composition root.

**Same genuine, unresolved ID-resolution gap as `AnthropicSchedulingPlanner`
/`AnthropicStaffPlanner` -- see that module's docstring for the full
explanation. A sharper version of the SAME problem, though, because of a
type-shape difference:** `ReminderPlan.appointment_id: str` (`ports/
reminder_planner.py`) is a REQUIRED, non-`Optional` field -- unlike
`SchedulingPlan.kwargs`/`StaffPlan.kwargs`'s dict shape, there is no way to
express "the model could not determine this" through an absent key here;
SOME string must always be returned.

**Resolution taken, explicit, not silently papered over:** if the message
literally contains an ID-shaped token (the one case this can genuinely
work -- e.g. a future quick-reply UI pasting a real id verbatim into the
message text; today's channels do not do this), it is used. Otherwise this
returns `appointment_id=""` -- a deliberately, obviously INVALID
placeholder, never a plausible-looking fabricated UUID. `SendReminder.
execute(appointment_id="")` (`modules/scheduling/application/use_cases/
send_reminder.py`) then fails LOUDLY: `SchedulingRepositoryPort.
get_appointment(tenant_id, "")` returns `None`, `SendReminder` raises
`AppointmentNotFoundError("")`, propagated by `persist_and_audit`'s own
"no try/except" contract to the central error handler -- the SAME safe,
loud-failure posture as the scheduling/staff planners' missing-kwarg
`TypeError`, adapted to this port's non-Optional return type. **Never
silently reminds the wrong appointment.**

**Practical consequence:** the `reminder` conversational intent is, as of
this batch, NOT functionally complete for natural-language appointment
references -- same open gap as `schedule`/`reschedule`/`cancel`/`staff`/
`shift`, for the same underlying reason (no lookup-by-natural-language-
reference tool call exists in this graph yet)."""

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.platform.inbound.graph.ports.reminder_planner import ReminderPlan
from app.shared_kernel.tenant_context import TenantContext

_SYSTEM_PROMPT = (
    "You are the reminder planner for Tony, a Peruvian clinic operations chat "
    "assistant. Extract the appointment identifier the user is referring to ONLY "
    "if it is literally present in their message (never invent or guess one -- "
    "leave it unset if it is not explicitly stated) and write a short, "
    "human-readable `summary` of the reminder in the user's own language (shown "
    "to the user as a confirmation prompt)."
)


class _ReminderExtraction(BaseModel):
    appointment_id: str | None = None
    summary: str = ""


class AnthropicReminderPlanner:
    """Duck-types `ReminderPlannerPort`."""

    def __init__(self, llm) -> None:
        self._structured = llm.with_structured_output(_ReminderExtraction)

    async def plan(self, ctx: TenantContext, *, message: str) -> ReminderPlan:
        # Deliberately NO try/except -- same posture as
        # `AnthropicSchedulingPlanner.plan`: `reminders_agent`'s only
        # outgoing edge is unconditional (`add_edge("reminders_agent",
        # "rbac_gate")`, `build_graph.py`).
        verdict = await self._structured.ainvoke(
            [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=message)]
        )
        return ReminderPlan(appointment_id=verdict.appointment_id or "", summary=verdict.summary)
