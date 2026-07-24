"""`persist_and_audit` node (design.md §8.2/§8.3, tasks.md task 11.5):
dispatches `proposed_action` to the real use case that actually executes it.
`ScheduleAppointment`/`RescheduleAppointment`/`CancelAppointment`/
`SendReminder`/`RegisterStaff`/`DeactivateStaff`/`CreateShift`/`EditShift`
ALL already audit INSIDE themselves, in the SAME transaction as the mutation
(confirmed: every one of their own module docstrings cites "ADR-3: audit in
the same transaction as the action") -- this node does NOT write a second,
separate audit entry; it only picks the right use case and calls it.

**Dispatch table keyed by `proposed_action.action` (an `ActionKey`) ->
composition-root builder.** `build_schedule_appointment`/
`build_reschedule_appointment`/`build_cancel_appointment`/
`build_send_reminder` already existed (tasks.md task 10.2); `build_register_
staff`/`build_deactivate_staff`/`build_create_shift`/`build_edit_shift` are
NEW this batch (`composition_root.py`'s own docstring, "Session 3") -- none
of the 4 staff use cases had ANY composition-root wiring before this task
(confirmed via `grep "^def build_" app/composition_root.py`, as this task's
own instructions required).

**`use_case.execute(ctx, **proposed_action.payload)` -- no re-parsing.**
`SchedulingPlannerPort`/`StaffPlannerPort`'s own docstrings both establish
`payload`/`kwargs` are shaped 1:1 to match the target use case's own
`**kwargs` -- this node trusts that contract rather than re-deriving
per-action argument names itself (that would duplicate what each planner
already owns, the same reasoning `confirmation_gate.py`'s `summary` field
already established for prompt text).

**`ActionOutcome`'s result shape is genuinely NOT uniform across the 8
dispatchable actions -- confirmed by reading all 8, not assumed.**
`ScheduleAppointment`/`RescheduleAppointment`/`CancelAppointment` return an
`Appointment` (has `.id`); `RegisterStaff`/`DeactivateStaff` return a
`StaffMember` (has `.id`); `CreateShift`/`EditShift` return a `Shift` (has
`.id`); `SendReminder` returns a plain `bool` (no `.id` at all -- `delivered`
status, itself never propagated to `ActionOutcome` since that dataclass has
no field for it, see below). `result_id = getattr(result, "id", None)`
handles all 8 without a per-action branch -- `None` for `SendReminder`'s
`bool` result is the correct, honest outcome, not a bug.

**`state.audit_ref` stays `None` from this node -- a genuine, FLAGGED gap,
not silently ignored.** None of the 8 use cases' `execute()` methods RETURN
the audit row id their internal `audit_log.record(...)` call produces (every
one of them calls `await self._audit_log.record(...)` and discards the
returned id) -- so "set `audit_ref` if the use case's result exposes one"
(this task's own wording) resolves to "never, for any of the 8, as they are
built today". Fixing this would mean either (a) every one of the 8 use
cases changing its return type to also expose the audit ref (a real,
cross-module signature change well beyond this node's own scope), or (b)
this node querying `audit_logs` back out for the row it suspects was just
written (fragile -- no natural unique handle to query by without inventing
one). Neither is done here; `respond`'s own composition (task 11.5, this
same batch) accounts for `audit_ref` possibly being `None` accordingly.
Flagged prominently for a future review/design revision, not swept under
the rug.

**No `try`/`except` here -- exceptions propagate.** design.md §8.3's edge
diagram has no "persist_and_audit failed" branch (`persist_and_audit`'s only
downstream edge is `[calendar_sync?] -> response_guard`, unconditional on
outcome) -- an exception from `use_case.execute()` (e.g.
`SlotUnavailableError`, `StaffNotAssignableError`) propagates all the way up
through `graph.ainvoke()` to the chat endpoint (task 11.7), which -- exactly
like every other router in this codebase -- does NOT catch it itself;
`register_exception_handlers` (task 10.3, already wired into `app/main.py`)
is the single translation boundary for it, same as the deterministic
web_form path. This means `ActionOutcome.success` is trivially always
`True` whenever this node returns a dict at all (a raise never produces one)
-- also flagged: `ActionOutcome.error`/`success=False` currently have no
code path that ever sets them from this node; `state.py`'s own docstring
already called `ActionOutcome` a "structural placeholder", and this batch
does not invent a failure-capturing behavior design.md's edges do not
describe."""

from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncConnection

from app.composition_root import (
    build_cancel_appointment,
    build_create_shift,
    build_deactivate_staff,
    build_edit_shift,
    build_register_staff,
    build_reschedule_appointment,
    build_schedule_appointment,
    build_send_reminder,
)
from app.modules.governance.rbac.domain.permission import ActionKey
from app.platform.inbound.graph.state import ActionOutcome, KurehaState

_DISPATCH: dict[ActionKey, Callable[[AsyncConnection], Any]] = {
    "appointment:create": build_schedule_appointment,
    "appointment:reschedule": build_reschedule_appointment,
    "appointment:cancel": build_cancel_appointment,
    "appointment:view": build_send_reminder,
    "staff:register": build_register_staff,
    "staff:deactivate": build_deactivate_staff,
    "shift:create": build_create_shift,
    "shift:edit": build_edit_shift,
}


class UnroutableActionError(Exception):
    """`proposed_action.action` has no entry in `_DISPATCH` -- structurally
    unreachable via design.md §8.3's edges in practice (every dispatched
    action already passed `rbac_gate` against the real `action_permissions`
    catalog, which `_DISPATCH`'s keys mirror exactly), guarded defensively
    rather than silently no-op-ing (same "fail loud, not silent" posture as
    `ActionRiskReader`'s deny-by-default for an unregistered key)."""

    def __init__(self, action: ActionKey) -> None:
        super().__init__(f"No persist_and_audit dispatch registered for action {action!r}")
        self.action = action


def make_persist_and_audit_node(conn: AsyncConnection, *, dispatch: dict[ActionKey, Callable] | None = None):
    """`dispatch` defaults to the real `_DISPATCH` table above -- overridable
    ONLY for tests (fakes with the same `Callable[[conn], use_case]` shape,
    see `test_persist_and_audit.py`), never in production wiring."""
    table = dispatch if dispatch is not None else _DISPATCH

    async def persist_and_audit(state: KurehaState) -> dict:
        proposed_action = state["proposed_action"]
        ctx = state["request_ctx"].to_tenant_context()

        builder = table.get(proposed_action.action)
        if builder is None:
            raise UnroutableActionError(proposed_action.action)

        use_case = builder(conn)
        result = await use_case.execute(ctx, **proposed_action.payload)

        outcome = ActionOutcome(success=True, result_id=getattr(result, "id", None), error=None)
        return {"outcome": outcome}

    return persist_and_audit
