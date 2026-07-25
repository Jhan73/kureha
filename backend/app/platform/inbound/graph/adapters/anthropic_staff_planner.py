"""`AnthropicStaffPlanner`: the real `StaffPlannerPort` adapter `staff_agent`
consumes (tasks.md task 12.7, design.md §8.10). Reasoner tier -- design.md
§8.10: "Similar a `scheduling_agent` para intents de personal y turnos."
Constructor-injected `ChatAnthropic`, built ONLY via `platform/inbound/graph/
adapters/llm.py`'s `build_chat_model("reasoner")` at the composition root.

**Same genuine, unresolved ID-resolution gap as `AnthropicSchedulingPlanner`
-- see that module's own docstring for the full explanation (RequestContext
vs TenantContext, no lookup port for "the staff member named X"/"the shift
tomorrow morning", `web_form` as the only production-ready path today).
Not repeated at length here.** `plan.kwargs` only ever contains fields the
model actually extracted -- never a key set to `None` -- so
`persist_and_audit`'s `use_case.execute(ctx, **payload)` fails loudly with a
clean `TypeError` for a genuinely missing required field, rather than
passing `None` into a use case with no safe handling for it.

**TWO structured-output schemas, chosen by `intent`, not one.** Unlike
`SchedulingPlannerPort` (where `action` is fully determined by `intent`
alone), a single `staff` intent covers TWO distinct actions
(`staff:register`/`staff:deactivate`) and a single `shift` intent covers
TWO more (`shift:create`/`shift:edit`) -- the model genuinely has to choose
between them based on the message, so `action` IS part of each schema's
`Literal`-constrained output here (unlike the scheduling planner's fully
deterministic map). `_StaffAction`/`_ShiftAction` are bound lazily, mirroring
`AnthropicScopePolicy`'s own `_bound_inbound`/`_bound_outbound` precedent --
only the schema the current `intent` actually needs is ever bound/called.

**`CreateShift`/`EditShift.execute()` take `starts_at`/`ends_at` as real
`datetime` objects, not strings** (verified by reading both use cases
directly) -- the model returns ISO-8601 strings (the only shape a
`Literal`/`str`-based structured-output schema can reliably produce), parsed
here via `datetime.fromisoformat()`. A malformed/unparseable string is
DROPPED from `kwargs` (never raises) -- the same "omit rather than fabricate
or crash" posture as every other unresolved field in this batch, and this
node (like `scheduling_agent`) has no failure-routing edge to fall back to
if `plan()` itself raised."""

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
