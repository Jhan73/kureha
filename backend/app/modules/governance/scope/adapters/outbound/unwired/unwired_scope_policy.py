"""`UnwiredClinicalScopePolicy`: duck-types `ClinicalScopePolicy`
(`governance/scope/domain/scope_policy.py`) -- same precedent as
`UnwiredStaffStatusAdapter`/`UnwiredAppointmentSnapshotAdapter`
(`modules/scheduling`/`modules/calendar`). `ClinicalScopePolicy`'s own
module docstring already named its real LLM-backed adapter as tasks.md task
12.3 (deliberately deferred) -- this placeholder is what lets
`clinical_scope_validator`/`response_guard` (tasks.md tasks 11.2/11.5) be
wired into a real, compilable graph (tasks.md task 11.6) before that later
task ships."""

from app.modules.governance.scope.domain.scope_policy import InboundScopeResult, OutboundScopeResult


class UnwiredClinicalScopePolicy:
    async def classify_inbound(self, ctx, message: str) -> InboundScopeResult:
        raise NotImplementedError(
            "UnwiredClinicalScopePolicy is a placeholder -- wire a real ClinicalScopePolicy "
            "implementation (tasks.md task 12.3) before clinical_scope_validator runs for real."
        )

    async def classify_outbound(self, ctx, chunk: str) -> OutboundScopeResult:
        raise NotImplementedError(
            "UnwiredClinicalScopePolicy is a placeholder -- wire a real ClinicalScopePolicy "
            "implementation (tasks.md task 12.3) before response_guard runs for real."
        )
