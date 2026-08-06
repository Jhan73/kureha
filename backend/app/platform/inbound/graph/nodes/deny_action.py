from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.platform.inbound.graph.state import KurehaState

_DENIAL_RESPONSE_TEXT = "No tienes permiso para realizar esta accion."


def make_deny_action_node(audit_log: AuditLogPort):
    async def deny_action(state: KurehaState) -> dict:
        proposed_action = state.get("proposed_action")
        ctx = state["request_ctx"]

        audit_ref = await audit_log.record(
            AuditEntry(
                tenant_id=ctx.tenant_id,
                site_id=ctx.site_id,
                actor_id=ctx.user_id,
                actor_type=AuditActorType.USER,
                action=AuditAction.RBAC_DENIED,
                object_type="proposed_action",
                object_id=proposed_action.action if proposed_action is not None else None,
            )
        )

        return {"response_text": _DENIAL_RESPONSE_TEXT, "audit_ref": audit_ref}

    return deny_action
