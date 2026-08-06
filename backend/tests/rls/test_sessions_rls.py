import sqlalchemy as sa

from tests.rls.helpers import seed_site, seed_tenant, seed_user, seed_user_session, set_app_context


async def test_user_sessions_cross_tenant_select_returns_zero_rows(rls_conn) -> None:
    tenant_a = await seed_tenant(rls_conn)
    tenant_b = await seed_tenant(rls_conn)
    site_b = await seed_site(rls_conn, tenant_b)
    user_b = await seed_user(rls_conn, tenant_b, site_b, role="reception")
    await seed_user_session(rls_conn, tenant_b, user_b, refresh_token_hash="hash-b")

    await set_app_context(rls_conn, tenant_id=tenant_a, role="admin")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM user_sessions"))).all()
    assert rows == []


async def test_user_sessions_same_tenant_visible_regardless_of_role(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    user_id = await seed_user(rls_conn, tenant_id, site_id, role="reception")
    session_id = await seed_user_session(rls_conn, tenant_id, user_id, refresh_token_hash="hash-a")

    await set_app_context(rls_conn, tenant_id=tenant_id, role="patient")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM user_sessions"))).all()
    assert [str(row.id) for row in rows] == [session_id]


async def test_rate_counters_has_no_rls_readable_across_tenants(rls_conn) -> None:
    await rls_conn.execute(
        sa.text(
            "INSERT INTO rate_counters (dimension, subject, window_start, count) "
            "VALUES ('auth_ip', 'no-rls-check', now(), 1)"
        )
    )
    rows = (
        await rls_conn.execute(
            sa.text("SELECT subject FROM rate_counters WHERE subject = 'no-rls-check'")
        )
    ).all()
    assert [row.subject for row in rows] == ["no-rls-check"]
