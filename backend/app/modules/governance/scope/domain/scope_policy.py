"""`ClinicalScopePolicy`: the inbound+outbound classifier interface design.md
§8.7 requires. This module defines the CONTRACT only -- the LLM-backed
classifier that reuses/extends the existing `clinical_scope_validator`
prompt lives in tasks.md Phase 12 (task 12.3), out of scope for task 3.4.

Kept in `domain/` (not `application/ports/`) to match design.md §2.5's
literal folder tree for this module -- `scope/domain/ # ClinicalScopePolicy:
modo inbound (intent) + outbound (respuesta)` -- even though this Protocol
will eventually be implemented by an LLM-calling adapter (normally a
`ports/driven/` concern). The classification RULE (which categories exist,
when they escalate/block) is domain policy; only its LLM-backed
implementation is infrastructure, and that adapter is a later phase.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from app.shared_kernel.tenant_context import TenantContext


class InboundScopeCategory(str, Enum):
    """design.md §8.7's three refusal triggers, plus the default in-scope
    outcome. Any category other than IN_SCOPE refuses the same way a direct
    diagnosis request would (same `escalate_human`/refusal path)."""

    IN_SCOPE = "in_scope"
    CLINICAL_DIAGNOSIS = "clinical_diagnosis"
    PROMPT_INJECTION = "prompt_injection"
    TENANT_SCOPE_LEAKAGE = "tenant_scope_leakage"


class OutboundScopeCategory(str, Enum):
    """design.md §8.7's independent output check -- runs regardless of
    whether the inbound filter caught anything."""

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
    """Implemented by an LLM-backed adapter (tasks.md Phase 12). RLS/RBAC
    remain the hard floor regardless of this classifier's verdict (design.md
    §8.7: "una injection nunca excede lo que datos/operaciones permiten").

    Both methods take `ctx: TenantContext` -- `TENANT_SCOPE_LEAKAGE` (in
    both categories) is a judgment relative to which tenant the current
    request belongs to; a classifier given only the raw text has no
    reference point to decide "mentions another clinic's patient" from
    "mentions this clinic's own patient." Matches the pattern
    `AuthorizationPort.is_allowed`/`CheckConsent.execute` already use.
    """

    async def classify_inbound(self, ctx: TenantContext, message: str) -> InboundScopeResult: ...

    async def classify_outbound(self, ctx: TenantContext, chunk: str) -> OutboundScopeResult: ...
