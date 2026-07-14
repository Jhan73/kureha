"""Task 4.1-4.3: RLS isolation for user_credentials (tenant-only, same shape
as user_sessions -- see migration 9f1c4a7b2e3d's docstring)."""

import sqlalchemy as sa

from tests.rls.helpers import seed_site, seed_tenant, seed_user, seed_user_credentials, set_app_context


async def test_user_credentials_cross_tenant_select_returns_zero_rows(rls_conn) -> None:
    tenant_a = await seed_tenant(rls_conn)
    tenant_b = await seed_tenant(rls_conn)
    site_b = await seed_site(rls_conn, tenant_b)
    user_b = await seed_user(rls_conn, tenant_b, site_b, role="reception")
    await seed_user_credentials(rls_conn, tenant_b, user_b, email="b@example.com")

    await set_app_context(rls_conn, tenant_id=tenant_a, role="admin")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM user_credentials"))).all()
    assert rows == []


async def test_user_credentials_same_tenant_visible_regardless_of_role(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    user_id = await seed_user(rls_conn, tenant_id, site_id, role="reception")
    credentials_id = await seed_user_credentials(rls_conn, tenant_id, user_id, email="a@example.com")

    await set_app_context(rls_conn, tenant_id=tenant_id, role="patient")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM user_credentials"))).all()
    assert [str(row.id) for row in rows] == [credentials_id]
