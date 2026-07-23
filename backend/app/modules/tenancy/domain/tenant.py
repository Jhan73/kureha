"""`Tenant` domain (design.md §2.5/§4.1): the persisted entity carrying the
clinic's own config -- NOT to be confused with `shared_kernel.TenantContext`
(the per-request identity value object every module imports). `Tenant` lives
here because knowing "is this clinic still active / what is its LLM daily
budget" is a tenancy concern, resolved once via a lookup use case and handed
to callers, never reached into by other modules directly (design.md §2.4:
business modules never import each other)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Tenant:
    """Projection of one `tenants` row (design.md §4.1's `CHECK (status IN
    ('active','suspended'))`, §19's `llm_daily_budget_tokens` column)."""

    id: str
    name: str
    status: str
    llm_daily_budget_tokens: int

    @property
    def is_active(self) -> bool:
        return self.status == "active"
