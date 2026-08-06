from app.modules.governance.scope.domain.scope_policy import InboundScopeResult, OutboundScopeResult


class UnwiredClinicalScopePolicy:
    async def classify_inbound(self, ctx, message: str) -> InboundScopeResult:
        raise NotImplementedError(
            "UnwiredClinicalScopePolicy is a placeholder -- wire a real ClinicalScopePolicy before using."
        )

    async def classify_outbound(self, ctx, chunk: str, *, callbacks=None) -> OutboundScopeResult:
        raise NotImplementedError(
            "UnwiredClinicalScopePolicy is a placeholder -- wire a real ClinicalScopePolicy before using."
        )
