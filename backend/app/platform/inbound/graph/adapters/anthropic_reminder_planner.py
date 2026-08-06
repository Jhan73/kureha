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
