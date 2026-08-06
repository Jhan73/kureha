from datetime import datetime
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.platform.inbound.graph.ports.staff_planner import StaffPlan
from app.shared_kernel.tenant_context import TenantContext

_STAFF_KWARGS_FIELDS: dict[str, tuple[str, ...]] = {
    "staff:register": ("site_id", "name", "operational_role", "user_id", "professional_id"),
    "staff:deactivate": ("staff_member_id",),
}
_SHIFT_KWARGS_FIELDS: dict[str, tuple[str, ...]] = {
    "shift:create": ("site_id", "staff_member_id", "starts_at", "ends_at"),
    "shift:edit": ("shift_id", "starts_at", "ends_at"),
}

_STAFF_SYSTEM_PROMPT = (
    "You are the staff-management planner for Tony, a Peruvian clinic operations "
    "chat assistant, used only by staff callers. Decide whether the user wants to "
    "REGISTER a new staff member (`staff:register`) or DEACTIVATE an existing one "
    "(`staff:deactivate`). Extract whatever concrete details are explicitly present "
    "(names, ids, operational role -- one of reception/professional/admin -- ONLY "
    "if the user literally states one; never invent or guess one) and write a "
    "short, human-readable `summary` of the intended action in the user's own "
    "language (shown to the user as a confirmation prompt)."
)
_SHIFT_SYSTEM_PROMPT = (
    "You are the shift-management planner for Tony, a Peruvian clinic operations "
    "chat assistant, used only by staff callers. Decide whether the user wants to "
    "CREATE a new shift (`shift:create`) or EDIT an existing one (`shift:edit`). "
    "Extract whatever concrete details are explicitly present (staff member "
    "identifiers, shift identifiers, start/end times as ISO-8601 timestamps ONLY "
    "if explicitly stated or unambiguously derivable from the message -- never "
    "invent or guess one) and write a short, human-readable `summary` of the "
    "intended action in the user's own language (shown to the user as a "
    "confirmation prompt)."
)


class _StaffAction(BaseModel):
    action: Literal["staff:register", "staff:deactivate"]
    site_id: str | None = None
    name: str | None = None
    operational_role: Literal["reception", "professional", "admin"] | None = None
    user_id: str | None = None
    professional_id: str | None = None
    staff_member_id: str | None = None
    summary: str = ""


class _ShiftAction(BaseModel):
    action: Literal["shift:create", "shift:edit"]
    site_id: str | None = None
    staff_member_id: str | None = None
    shift_id: str | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    summary: str = ""


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class AnthropicStaffPlanner:
    """Duck-types `StaffPlannerPort`."""

    def __init__(self, llm) -> None:
        self._llm = llm
        self._staff_runnable = None
        self._shift_runnable = None

    def _bound_staff(self):
        if self._staff_runnable is None:
            self._staff_runnable = self._llm.with_structured_output(_StaffAction)
        return self._staff_runnable

    def _bound_shift(self):
        if self._shift_runnable is None:
            self._shift_runnable = self._llm.with_structured_output(_ShiftAction)
        return self._shift_runnable

    async def plan(self, ctx: TenantContext, *, intent: str, message: str) -> StaffPlan:
        # Deliberately NO try/except -- same posture as
        # `AnthropicSchedulingPlanner.plan` (see that module's docstring):
        # `staff_agent`'s only outgoing edge is unconditional
        # (`add_edge("staff_agent", "rbac_gate")`, `build_graph.py`).
        if intent == "staff":
            verdict = await self._bound_staff().ainvoke(
                [SystemMessage(content=_STAFF_SYSTEM_PROMPT), HumanMessage(content=message)]
            )
            fields = _STAFF_KWARGS_FIELDS[verdict.action]
        elif intent == "shift":
            verdict = await self._bound_shift().ainvoke(
                [SystemMessage(content=_SHIFT_SYSTEM_PROMPT), HumanMessage(content=message)]
            )
            fields = _SHIFT_KWARGS_FIELDS[verdict.action]
        else:
            raise ValueError(f"AnthropicStaffPlanner.plan called with unsupported intent {intent!r}")

        kwargs: dict = {}
        for name in fields:
            value = getattr(verdict, name)
            if name in ("starts_at", "ends_at"):
                value = _parse_datetime(value)
            if value is not None:
                kwargs[name] = value

        return StaffPlan(action=verdict.action, kwargs=kwargs, summary=verdict.summary)
