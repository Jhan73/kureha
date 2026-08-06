from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from app.shared_kernel.tenant_context import TenantContext


class InboundScopeCategory(str, Enum):
    IN_SCOPE = "in_scope"
    CLINICAL_DIAGNOSIS = "clinical_diagnosis"
    PROMPT_INJECTION = "prompt_injection"
    TENANT_SCOPE_LEAKAGE = "tenant_scope_leakage"


class OutboundScopeCategory(str, Enum):
    SAFE = "safe"
    CLINICAL_CONTENT = "clinical_content"
    TENANT_SCOPE_LEAKAGE = "tenant_scope_leakage"


@dataclass(frozen=True, slots=True)
class InboundScopeResult:
    category: InboundScopeCategory
    should_escalate: bool


@dataclass(frozen=True, slots=True)
class OutboundScopeResult:
    category: OutboundScopeCategory
    should_block: bool


class ClinicalScopePolicy(Protocol):
    """LLM classifier seam; RLS/RBAC remain the hard floor. ctx needed for tenant-leakage checks."""

    async def classify_inbound(self, ctx: TenantContext, message: str) -> InboundScopeResult: ...

    async def classify_outbound(self, ctx: TenantContext, chunk: str) -> OutboundScopeResult: ...
