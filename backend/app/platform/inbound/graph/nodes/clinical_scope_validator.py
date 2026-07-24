"""`clinical_scope_validator` node, INBOUND mode only (design.md
§8.2/§8.7, tasks.md task 11.2): delegates to `ClinicalScopePolicy.
classify_inbound` (governance/scope/domain/scope_policy.py) and sets
`state.scope_ok`. Outbound mode (`response_guard`, validating the agent's
own response before it reaches the user) is a DIFFERENT node -- tasks.md
task 11.5, batch 2/3, out of scope here.

`ClinicalScopePolicy` already exists as a Protocol-only seam (its own
module docstring: the LLM-backed adapter is tasks.md task 12.3,
deliberately deferred) -- this node consumes that seam as-is, adding no
adapter of its own. Any category other than `IN_SCOPE` refuses the same
way a direct diagnosis request would (design.md §8.7); this node only
surfaces the boolean verdict `scope_ok` -- the actual escalation branch is
the `clinical_scope_validator ─ scope_ok=False ─► escalate_human` edge
(design.md §8.3), wired in task 11.6."""

from app.modules.governance.scope.domain.scope_policy import ClinicalScopePolicy, InboundScopeCategory
from app.platform.inbound.graph.state import KurehaState


def make_clinical_scope_validator_node(scope_policy: ClinicalScopePolicy):
    async def clinical_scope_validator(state: KurehaState) -> dict:
        result = await scope_policy.classify_inbound(
            state["request_ctx"].to_tenant_context(), state["channel_message"]
        )
        return {"scope_ok": result.category is InboundScopeCategory.IN_SCOPE}

    return clinical_scope_validator
