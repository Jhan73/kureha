"""`hitl_approval` node (design.md §8.3/§8.4 point 1, tasks.md task 11.4):
the graph's ONE `interrupt()` (design.md: "UNICO interrupt del MVP"). Pauses
a mutating action for staff approval when `risk_level=="high"`
(`scheduling_agent`'s own `RiskPolicy` computation) **or**
`action_permissions.requires_hitl` is set for `proposed_action.action` --
this node reads `requires_hitl` itself, live, via `ActionRiskPort` (this
same task's new port, `governance/rbac/application/ports/driven/
action_risk.py`), independently of whichever upstream condition
(`route_by_risk`, tasks.md task 11.6, not yet built) actually routed
execution here: it needs the live value regardless, to build correct
audit-trail language/payload, and cannot assume "I was only ever routed
here because requires_hitl was true" without re-deriving that fact itself.

Uses LangGraph's real `interrupt()` primitive (`langgraph.types.interrupt`),
NOT a bespoke pause mechanism -- `Command(resume=ApprovalDecision(...))`
resumes with the staff approver's decision (`state.py`'s own
`ApprovalDecision` placeholder, defined in batch 1 for exactly this task).
**Both branches are audited, approve AND reject** (design.md: "la decision
se audita apruebe o rechace") -- `AuditAction.HITL_APPROVE`/`HITL_REJECT`
(already defined, `governance/audit/domain/audit_entry.py`), via the
existing `AuditLogPort`/`PostgresAuditLog` (unchanged).

**Connection-ownership decision, judged against `calendar_oauth.py`'s
`_audit_csrf_attempt` precedent -- not copied blindly.** That helper opens a
FRESH, independently-committed connection specifically because it audits a
CSRF-attempt right before RAISING an exception that the access-control
middleware's `_forward_with_session` then rolls back (`commit = status_code
< 500` never evaluates for a raised exception that never reaches a
response) -- writing on the shared request connection would silently roll
the audit row back together with the deny. That failure mode does NOT apply
here: `hitl_approval` never raises on either branch (approved routes to
`persist_and_audit`, rejected routes to `escalate_human`, both via a normal
`return {...}` node output -- matching this whole package's "orchestration,
never control flow via exceptions" convention, see `rbac_gate`/
`consent_gate`). This node therefore takes `AuditLogPort` injected via the
closure, exactly like every other node in this package injects its
collaborators (`AuthorizeAction` in `rbac_gate`, `CheckConsent` in
`consent_gate`) -- composition (wherever batch 3's `build_graph()` wires
nodes) is expected to hand this node the SAME request-scoped `AuditLogPort`/
connection every other node/use case in the same request shares, so the
HITL-decision audit row commits atomically with whatever `persist_and_audit`
(task 11.5) does next in the SAME transaction, not a separately-committed
one.

**Interrupt payload shape (design.md §8.4 point 1's literal field list:
`{action_type, appointment_id(s), patient_ref, professional_from,
professional_to, reason, requested_by}`) -- best-effort extraction, flagged
open question for batch 3/whoever builds a real bulk-cancel use case.**
`ProposedAction.payload` is a generic `dict[str, Any]` shaped 1:1 to match
whichever scheduling use case's OWN kwargs (`ScheduleAppointment.execute`:
`patient_id`/`professional_id`/`site_id`/`availability_id`;
`RescheduleAppointment.execute`: `appointment_id`/`new_availability_id`;
`CancelAppointment.execute`: `appointment_id` only -- no bulk-cancel use
case exists anywhere in this codebase yet; `appointment:cancel_bulk` is
still an `action_catalog.py`-documented FUTURE key with no call site).
`SchedulingPlannerPort`'s own `appointment_ids`/`requested_professional_id`/
`target_professional_id` fields (used by `scheduling_agent` to compute
`risk_level`) are explicitly NOT copied into `ProposedAction.payload`
(`scheduling_planner.py`'s own docstring) -- so by the time this node runs,
that risk-relevant detail is already GONE from `proposed_action`; only the
use-case-kwargs-shaped `payload` survives. This node extracts what it
defensively can (`payload.get(...)`, never assumes a key exists) rather than
inventing a stronger contract `ProposedAction` does not actually offer today
-- flagged prominently for batch 3: `ProposedAction` may need a dedicated
risk-context-shaped field (surviving from `SchedulingPlan` through to here)
if a real bulk-cancel use case is ever built, since `payload` alone cannot
carry it."""

from langgraph.types import interrupt

from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.governance.rbac.application.ports.driven.action_risk import ActionRiskPort
from app.platform.inbound.graph.state import ApprovalDecision, KurehaState


def _extract_appointment_ids(payload: dict) -> list[str]:
    """Best-effort -- see this module's docstring for why `payload` cannot
    reliably carry a bulk list today."""
    if "appointment_ids" in payload:
        return list(payload["appointment_ids"])
    if "appointment_id" in payload:
        return [payload["appointment_id"]]
    return []


def make_hitl_approval_node(action_risk: ActionRiskPort, audit_log: AuditLogPort):
    async def hitl_approval(state: KurehaState) -> dict:
        proposed_action = state["proposed_action"]
        ctx = state["request_ctx"]
        risk_config = await action_risk.get(proposed_action.action)

        payload = proposed_action.payload
        interrupt_payload = {
            "action_type": proposed_action.action,
            "appointment_ids": _extract_appointment_ids(payload),
            "patient_ref": payload.get("patient_id") or ctx.patient_id,
            "professional_from": payload.get("professional_id"),
            "professional_to": payload.get("new_professional_id") or payload.get("professional_id"),
            "reason": proposed_action.summary,
            "requested_by": ctx.user_id,
            "requires_hitl": risk_config.requires_hitl,
        }

        decision: ApprovalDecision = interrupt(interrupt_payload)

        audit_action = AuditAction.HITL_APPROVE if decision.approved else AuditAction.HITL_REJECT
        audit_ref = await audit_log.record(
            AuditEntry(
                tenant_id=ctx.tenant_id,
                site_id=ctx.site_id,
                actor_id=decision.approved_by,
                actor_type=AuditActorType.USER,
                action=audit_action,
                object_type="proposed_action",
                object_id=proposed_action.action,
                reason=decision.reason,
                payload=interrupt_payload,
            )
        )

        return {"approval": decision, "audit_ref": audit_ref}

    return hitl_approval
