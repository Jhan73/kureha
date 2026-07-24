"""`consent_gate` node (design.md §8.2/§8.3, tasks.md task 11.2):
precondition gate for patient-data-touching intents (`schedule`,
`reschedule`, `cancel`, `reminder`). Delegates to the existing
`CheckConsent` use case (governance/consent/application/use_cases/
check_consent.py, design.md §11) and sets `state.consent_ok = (result ==
ConsentCheckResult.CURRENT)`.

**Staff/shift bypass (design.md §8.3's note right after the edges
diagram):** `staff`/`shift` intents never carry patient data in scope --
the node short-circuits to `consent_ok=True` WITHOUT calling
`CheckConsent`, avoiding an unnecessary consents query for a
receptionist/staff-registration turn.

**Flagged gap, not silently resolved:** this node resolves the patient to
check consent for from `state.request_ctx.patient_id` -- correct for
`patient_chat`'s self-service flows (`ctx.role == "patient"`,
`ctx.patient_id` is the caller's own id), but `consent_gate` runs BEFORE
`resolve_toolset`/`scheduling_agent` in the edge order (design.md §8.3), so
a `staff_copilot`-channel intent where reception schedules an appointment
ON BEHALF OF a different patient has no `patient_id` in scope yet at this
point in the graph -- the target patient only appears later, inside
`proposed_action.payload`, once `scheduling_agent` plans the action. When
`request_ctx.patient_id` is `None` for a patient-touching intent, this
node DENIES (`consent_ok=False`) rather than skip the check --
deny-by-default, consistent with every other governance gate in this
codebase (RBAC §5.2, RLS's own deny-by-default posture) -- but this means
staff-initiated scheduling FOR another patient cannot pass `consent_gate`
as currently positioned in the graph. Not resolved in this batch (task
11.2's scope is the node itself, not a graph-shape change) -- flagged here
for whoever builds task 11.6's edge wiring / a future design revision to
decide whether `consent_gate` needs to move after `scheduling_agent` for
the copilot channel, or `RequestContext` needs a separate "target patient"
concept."""

from app.modules.governance.consent.application.use_cases.check_consent import CheckConsent
from app.modules.governance.consent.domain.consent_policy import ConsentCheckResult
from app.platform.inbound.graph.state import KurehaState


def make_consent_gate_node(check_consent: CheckConsent):
    async def consent_gate(state: KurehaState) -> dict:
        if state["intent"] in ("staff", "shift"):
            return {"consent_ok": True}

        ctx = state["request_ctx"]
        if ctx.patient_id is None:
            return {"consent_ok": False}

        result = await check_consent.execute(ctx.to_tenant_context(), patient_id=ctx.patient_id)
        return {"consent_ok": result is ConsentCheckResult.CURRENT}

    return consent_gate
