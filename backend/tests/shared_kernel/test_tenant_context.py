import pytest

from app.shared_kernel.tenant_context import TenantContext


def test_tenant_context_holds_the_four_identity_fields() -> None:
    ctx = TenantContext(tenant_id="t1", role="reception", site_id="s1", actor_id="u1")

    assert ctx.tenant_id == "t1"
    assert ctx.role == "reception"
    assert ctx.site_id == "s1"
    assert ctx.actor_id == "u1"


def test_tenant_context_site_id_and_actor_id_default_to_none() -> None:
    ctx = TenantContext(tenant_id="t1", role="admin")

    assert ctx.site_id is None
    assert ctx.actor_id is None


def test_tenant_context_is_immutable() -> None:
    ctx = TenantContext(tenant_id="t1", role="admin")

    with pytest.raises(AttributeError):
        ctx.tenant_id = "t2"  # type: ignore[misc]
