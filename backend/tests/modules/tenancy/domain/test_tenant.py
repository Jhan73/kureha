"""Task 6.1: `Tenant` domain value object (design.md §4.1's `tenants` table
shape + §19's `llm_daily_budget_tokens`). Pure -- no IO."""

from app.modules.tenancy.domain.tenant import Tenant


def test_tenant_is_active_when_status_is_active() -> None:
    tenant = Tenant(id="t1", name="Test Clinic", status="active", llm_daily_budget_tokens=100_000)

    assert tenant.is_active is True


def test_tenant_is_not_active_when_status_is_suspended() -> None:
    tenant = Tenant(id="t1", name="Test Clinic", status="suspended", llm_daily_budget_tokens=100_000)

    assert tenant.is_active is False


def test_tenant_is_immutable() -> None:
    tenant = Tenant(id="t1", name="Test Clinic", status="active", llm_daily_budget_tokens=100_000)

    try:
        tenant.name = "Other Clinic"  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("Tenant must be frozen")
