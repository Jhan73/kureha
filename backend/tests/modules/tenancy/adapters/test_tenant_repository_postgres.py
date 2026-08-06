from tests.schema.helpers import make_tenant

from app.modules.tenancy.adapters.outbound.postgres.tenant_repository import PostgresTenantRepository


async def test_get_by_id_returns_the_tenant(db_conn) -> None:
    tenant_id = await make_tenant(db_conn, name="Clinica Real")

    repository = PostgresTenantRepository(db_conn)
    tenant = await repository.get_by_id(tenant_id)

    assert tenant is not None
    assert tenant.id == tenant_id
    assert tenant.name == "Clinica Real"
    assert tenant.status == "active"
    assert tenant.llm_daily_budget_tokens == 100_000


async def test_get_by_id_returns_none_for_unknown_tenant(db_conn) -> None:
    # Not the nil UUID: that is SYSTEM_TENANT_ID, a real (suspended) row
    # seeded by migration `a1c7e9d34f02` -- see `system_tenant.py`.
    repository = PostgresTenantRepository(db_conn)

    assert await repository.get_by_id("11111111-1111-1111-1111-111111111111") is None


async def test_get_by_id_reflects_suspended_status(db_conn) -> None:
    import sqlalchemy as sa

    tenant_id = await make_tenant(db_conn)
    await db_conn.execute(sa.text("UPDATE tenants SET status = 'suspended' WHERE id = :id"), {"id": tenant_id})

    repository = PostgresTenantRepository(db_conn)
    tenant = await repository.get_by_id(tenant_id)

    assert tenant is not None
    assert tenant.status == "suspended"
