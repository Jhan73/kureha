"""`CheckConsent` use case (design.md §11): the precondition every mutating
scheduling/staff use case runs before touching a patient's data. Pure
orchestration -- delegates the actual verdict to `ConsentPolicy.evaluate`."""

from app.modules.governance.consent.application.ports.driven.consent_registry import ConsentRegistryPort
from app.modules.governance.consent.domain.consent_policy import ConsentCheckResult, ConsentPolicy
from app.shared_kernel.tenant_context import TenantContext


class CheckConsent:
    def __init__(self, consent_registry: ConsentRegistryPort) -> None:
        self._consent_registry = consent_registry

    async def execute(self, ctx: TenantContext, *, patient_id: str) -> ConsentCheckResult:
        # `get_consent_check_data` resolves policy + consent in a single
        # round trip. An earlier version called `get_current_policy` and
        # `get_latest_consent` sequentially (two round trips); a version
        # using `asyncio.gather` over the same shared `AsyncConnection` was
        # tried and reverted -- concurrent `.execute()` calls on one asyncpg
        # connection are not a documented-safe pattern, and a fast localhost
        # test passing doesn't prove it's safe under real network latency.
        # A single combined query sidesteps the question entirely.
        policy, consent = await self._consent_registry.get_consent_check_data(ctx.tenant_id, patient_id)
        return ConsentPolicy.evaluate(
            current_version=policy.version if policy is not None else None,
            consent=consent,
        )
