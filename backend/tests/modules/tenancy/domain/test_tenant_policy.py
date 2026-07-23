"""Task 6.1: `TenantPolicy` -- pure rule gating whether a tenant is usable
for a request (design.md §3.1's `tenants.status` CHECK: 'active'|'suspended').
Mirrors `SessionPolicy`/`ConsentPolicy`'s shape: no IO, the use case owns the
lookup, this owns the verdict."""

from app.modules.tenancy.domain.tenant import Tenant
from app.modules.tenancy.domain.tenant_policy import TenantPolicy


def _tenant(*, status: str) -> Tenant:
    return Tenant(id="t1", name="Test Clinic", status=status, llm_daily_budget_tokens=100_000)


def test_active_tenant_is_usable() -> None:
    assert TenantPolicy.is_usable(_tenant(status="active")) is True


def test_suspended_tenant_is_not_usable() -> None:
    assert TenantPolicy.is_usable(_tenant(status="suspended")) is False
