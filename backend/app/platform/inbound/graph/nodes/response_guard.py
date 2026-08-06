from app.modules.governance.scope.domain.scope_policy import ClinicalScopePolicy, OutboundScopeCategory
from app.platform.inbound.graph.state import KurehaState


def make_response_guard_node(scope_policy: ClinicalScopePolicy):
    async def response_guard(state: KurehaState) -> dict:
        ctx = state["request_ctx"].to_tenant_context()
        result = await scope_policy.classify_outbound(ctx, state.get("response_text") or "")
        return {"response_scope_ok": result.category is OutboundScopeCategory.SAFE}

    return response_guard
