from app.modules.governance.scope.domain.scope_policy import ClinicalScopePolicy, InboundScopeCategory
from app.platform.inbound.graph.state import KurehaState


def make_clinical_scope_validator_node(scope_policy: ClinicalScopePolicy):
    async def clinical_scope_validator(state: KurehaState) -> dict:
        result = await scope_policy.classify_inbound(
            state["request_ctx"].to_tenant_context(), state["channel_message"]
        )
        return {"scope_ok": result.category is InboundScopeCategory.IN_SCOPE}

    return clinical_scope_validator
