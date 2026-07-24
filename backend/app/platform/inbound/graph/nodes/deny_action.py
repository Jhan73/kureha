"""`deny_action` node (design.md §8.2/§8.3, tasks.md task 11.5): the exit
node `rbac_gate ─ rbac_ok=False ─► deny_action ─► respond ─► END` reaches.
Audits `AuditAction.RBAC_DENIED` (already defined,
`governance/audit/domain/audit_entry.py`) and sets a curated
`response_text` -- mirroring `errors.py`'s own "curated user_message, never
`str(exception)`" convention (that module's own docstring: "no response
path can accidentally leak a stack trace... or a secret"). The SAME
principle applies here: `proposed_action`/RBAC internals (which specific
permission table row denied it, why) never leak into the user-facing text,
only a generic "you don't have permission" message -- exactly the wording
`errors.py`'s own `ActionNotPermittedError` mapping already uses for the
deterministic (web_form) path, kept consistent between both surfaces."""

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
