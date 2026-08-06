from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Immutable request identity; `site_id`/`actor_id` may be None."""

    tenant_id: str
    role: str
    site_id: str | None = None
    actor_id: str | None = None
