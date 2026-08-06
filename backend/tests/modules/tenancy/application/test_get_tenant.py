import pytest

from app.modules.tenancy.application.use_cases.get_tenant import GetTenant
from app.modules.tenancy.domain.errors import TenantNotFoundError, TenantSuspendedError
from app.modules.tenancy.domain.tenant import Tenant


class _FakeTenantRepository:
    def __init__(self, *, tenant: Tenant | None) -> None:
        self._tenant = tenant

    async def get_by_id(self, tenant_id: str) -> Tenant | None:
        return self._tenant


async def test_returns_the_tenant_when_active() -> None:
    tenant = Tenant(id="t1", name="Test Clinic", status="active", llm_daily_budget_tokens=100_000)
    use_case = GetTenant(_FakeTenantRepository(tenant=tenant))

    result = await use_case.execute("t1")

    assert result == tenant


async def test_raises_not_found_when_no_matching_row() -> None:
    use_case = GetTenant(_FakeTenantRepository(tenant=None))

    with pytest.raises(TenantNotFoundError):
        await use_case.execute("unknown")


async def test_raises_suspended_when_status_is_not_active() -> None:
    tenant = Tenant(id="t1", name="Test Clinic", status="suspended", llm_daily_budget_tokens=100_000)
    use_case = GetTenant(_FakeTenantRepository(tenant=tenant))

    with pytest.raises(TenantSuspendedError):
        await use_case.execute("t1")
