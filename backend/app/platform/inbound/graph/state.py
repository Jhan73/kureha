"""`KurehaState` (design.md §8.1, tasks.md task 11.1): the LangGraph state
shape every node in `platform/inbound/graph/` reads from and returns a
partial update to. Field list, names, and types are copied verbatim from
design.md §8.1's `TypedDict` -- do not rename/reshape fields here without
updating design.md first (backend/AGENTS.md's folder-layout rule extends to
this contract, since every downstream node/edge in tasks.md Phase 11-12
depends on these exact keys).

**`RequestContext` vs `TenantContext` -- a deliberate, documented decision,
not an oversight.** design.md §8.1's own inline comment for `request_ctx`
reads: "tenant_id, site_id, role, user_id, patient_id/professional_id".
`app.shared_kernel.tenant_context.TenantContext` (used pervasively by every
existing use case's `execute(ctx: TenantContext, ...)` signature) carries
only `tenant_id`, `role`, `site_id`, `actor_id` -- it has NO `patient_id`/
`professional_id` fields. These are not the same type, and this is not a
naming coincidence to silently paper over:

- `TenantContext` is deliberately minimal (its own docstring: "the four
  pieces of request-scoped identity RLS's `SET LOCAL` GUCs and RBAC's
  precedence resolution both need"). Existing use cases that need a
  patient/professional id already take it as an explicit `execute(..., *,
  patient_id=...)` keyword argument (see `CheckConsent.execute`,
  `ScheduleAppointment.execute`) -- they do NOT expect it to ride inside the
  context object.
- The graph, however, needs `patient_id`/`professional_id` as part of the
  ambient per-turn identity (e.g. `consent_gate` resolving WHICH patient's
  consent to check, `RequestContext` disambiguating a `patient_chat` caller
  from a `staff_copilot` caller) -- a concern `TenantContext` was never
  designed to carry, and widening the shared-kernel type would ripple
  `patient_id`/`professional_id` into every module's `TenantContext`
  consumer for a concern only the graph has.

**Resolution:** `RequestContext` is defined here, as a graph-local platform
type (NOT in `shared_kernel/`, which is deliberately "value objects only,
no IO, no business logic" shared by literally every module -- this type is
graph-specific enrichment, not a primitive every module needs). It exposes
`to_tenant_context()`, an explicit, visible conversion any node calls right
before invoking a business-module use case that expects a `TenantContext`.
This keeps the two types honestly separate instead of quietly overloading
`TenantContext` with fields most of its callers never use.

`ProposedAction`/`ApprovalDecision`/`ActionOutcome` do not exist anywhere
else in the codebase before this batch -- defined here for the same reason:
design.md §8.1 names them as part of `KurehaState`'s contract but never
gives their field-level shape (only prose describing what nodes DO with
them, §8.2-§8.4/§8.9). `ProposedAction.payload` is deliberately a generic
`dict[str, Any]` rather than a union of per-intent dataclasses -- it is
built by whichever specialist node (`scheduling_agent`/`reminders_agent`/
`staff_agent`) plans the action, shaped 1:1 to match that action's eventual
use case's `**kwargs` (e.g. `ScheduleAppointment.execute`'s own keyword
arguments), and consumed the same way by `persist_and_audit` (tasks.md task
11.5, batch 2/3): `use_case.execute(ctx, **proposed_action.payload)`. A
fixed dataclass per action type would need to grow with every new business
action; the generic payload dict does not."""

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from app.modules.governance.rbac.domain.permission import ActionKey
from app.shared_kernel.tenant_context import TenantContext


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Graph-local identity context (design.md §8.1's `request_ctx` comment)
    -- see this module's docstring for why it is not `TenantContext`."""

    tenant_id: str
    role: str
    site_id: str | None = None
    user_id: str | None = None
    patient_id: str | None = None
    professional_id: str | None = None

    def to_tenant_context(self) -> TenantContext:
        """The explicit, visible conversion every node calls right before
        invoking a business-module use case -- `actor_id` maps from
        `user_id` (the acting user, regardless of `patient_id`/
        `professional_id`, which `TenantContext` has no room for)."""
        return TenantContext(tenant_id=self.tenant_id, role=self.role, site_id=self.site_id, actor_id=self.user_id)


@dataclass(frozen=True, slots=True)
class ProposedAction:
    """A specialist node's (not-yet-executed) plan -- see this module's
    docstring for why `payload` is a generic dict rather than a per-intent
    dataclass."""

    action: ActionKey
    is_mutating: bool
    payload: dict[str, Any] = field(default_factory=dict)
    summary: str = ""


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """`hitl_approval`'s `Command(resume=...)` payload (design.md §8.4 point
    1) -- structural placeholder for tasks.md task 11.4 (batch 2), which
    owns the interrupt/resume wiring itself; defined here only because
    `KurehaState` references the type."""

    approved: bool
    approved_by: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    """`persist_and_audit`'s result (tasks.md task 11.5, batch 2/3) --
    structural placeholder for the same reason as `ApprovalDecision` above."""

    success: bool
    result_id: str | None = None
    error: str | None = None


class KurehaState(TypedDict):
    """Verbatim field list from design.md §8.1."""

    request_ctx: RequestContext
    channel: Literal["web_form", "patient_chat", "staff_copilot"]
    channel_message: str
    intent: (
        Literal[
            "schedule",
            "reschedule",
            "cancel",
            "reminder",
            "staff",
            "shift",
            "greeting",
            "capability_query",
            "small_talk",
            "unknown",
        ]
        | None
    )
    scope_ok: bool | None
    consent_ok: bool | None
    allowed_actions: list[str] | None
    proposed_action: ProposedAction | None
    rbac_ok: bool | None
    risk_level: Literal["low", "high"] | None
    confirmation: Literal["not_required", "needed", "affirmed"] | None
    approval: ApprovalDecision | None
    outcome: ActionOutcome | None
    audit_ref: str | None
    response_text: str | None
    response_scope_ok: bool | None
    calendar_sync_status: Literal["pending", "ok", "failed", "n/a"] | None
    suggestions: list[str] | None
