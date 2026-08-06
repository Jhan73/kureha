from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.platform.inbound.graph.state import KurehaState

_ESCALATION_RESPONSE_TEXT = (
    "Tu solicitud fue derivada a un miembro de nuestro equipo, quien te va a contactar a la brevedad."
)


def _escalation_reason(state: KurehaState) -> str:
    if state.get("scope_ok") is False:
        return "scope_violation"
    if state.get("consent_ok") is False:
        return "consent_not_current"
    approval = state.get("approval")
    if approval is not None and not approval.approved:
        return "hitl_rejected"
    if state.get("response_scope_ok") is False:
        return "response_scope_violation"
    if state.get("intent") == "unknown":
        return "unknown_intent"
    return "escalated"


def make_escalate_human_node(audit_log: AuditLogPort):
    async def escalate_human(state: KurehaState) -> dict:
        ctx = state["request_ctx"]
        proposed_action = state.get("proposed_action")

        audit_ref = await audit_log.record(
            AuditEntry(
                tenant_id=ctx.tenant_id,
                site_id=ctx.site_id,
                actor_id=ctx.user_id,
                actor_type=AuditActorType.USER,
                action=AuditAction.SCOPE_ESCALATE,
                object_type="proposed_action" if proposed_action is not None else "message",
                object_id=proposed_action.action if proposed_action is not None else None,
                reason=_escalation_reason(state),
            )
        )

        return {"response_text": _ESCALATION_RESPONSE_TEXT, "audit_ref": audit_ref}

    return escalate_human
