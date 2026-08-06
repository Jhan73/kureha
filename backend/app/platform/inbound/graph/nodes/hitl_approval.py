from langgraph.types import interrupt

from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.governance.rbac.application.ports.driven.action_risk import ActionRiskPort
from app.platform.inbound.graph.state import ApprovalDecision, KurehaState


def _extract_appointment_ids(payload: dict) -> list[str]:
    """Best-effort extract from payload keys appointment_ids / appointment_id."""
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
