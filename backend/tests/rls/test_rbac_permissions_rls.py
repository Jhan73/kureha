"""Task 2.9: RLS isolation for role_permissions/user_permissions (tenant-only,
design.md §4.4), plus confirmation that `action_permissions` (the global
catalog) has no RLS at all -- any role/tenant can read it."""

import sqlalchemy as sa

from tests.rls.helpers import seed_site, seed_tenant, seed_user, set_app_context


async def _seed_action(conn, key="rls-test-action"):
    await conn.execute(
        sa.text("INSERT INTO action_permissions (key, description) VALUES (:key, 'x')"),
        {"key": key},
    )


async def test_action_permissions_readable_by_any_role_no_rls(rls_conn) -> None:
    await _seed_action(rls_conn)

    tenant_id = await seed_tenant(rls_conn)
    await set_app_context(rls_conn, tenant_id=tenant_id, role="patient")
    rows = (
        await rls_conn.execute(
            sa.text("SELECT key FROM action_permissions WHERE key = 'rls-test-action'")
        )
    ).all()
    assert [row.key for row in rows] == ["rls-test-action"]


async def test_role_permissions_cross_tenant_select_returns_zero_rows(rls_conn) -> None:
    await _seed_action(rls_conn)
    tenant_a = await seed_tenant(rls_conn)
    tenant_b = await seed_tenant(rls_conn)

    await set_app_context(rls_conn, tenant_id=tenant_b, role="admin")
    await rls_conn.execute(
        sa.text(
            "INSERT INTO role_permissions (tenant_id, role, action, allowed) "
            "VALUES (:t, 'reception', 'rls-test-action', true)"
        ),
        {"t": tenant_b},
    )

    await set_app_context(rls_conn, tenant_id=tenant_a, role="admin")
    rows = (await rls_conn.execute(sa.text("SELECT tenant_id FROM role_permissions"))).all()
    assert rows == []


async def test_role_permissions_any_role_within_tenant_can_read(rls_conn) -> None:
    """RBAC's own authorization gate is a separate plane (§5.1) -- RLS here
    only enforces the tenant boundary, not who may read/write the grant
    table itself."""
    await _seed_action(rls_conn)
    tenant_id = await seed_tenant(rls_conn)

    await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
    await rls_conn.execute(
        sa.text(
            "INSERT INTO role_permissions (tenant_id, role, action, allowed) "
            "VALUES (:t, 'reception', 'rls-test-action', true)"
        ),
        {"t": tenant_id},
    )

    await set_app_context(rls_conn, tenant_id=tenant_id, role="patient")
    rows = (await rls_conn.execute(sa.text("SELECT role FROM role_permissions"))).all()
    assert [row.role for row in rows] == ["reception"]


async def test_user_permissions_cross_tenant_select_returns_zero_rows(rls_conn) -> None:
    await _seed_action(rls_conn)
    tenant_a = await seed_tenant(rls_conn)
    tenant_b = await seed_tenant(rls_conn)
    site_b = await seed_site(rls_conn, tenant_b)
    user_b = await seed_user(rls_conn, tenant_b, site_b, role="reception")

    await set_app_context(rls_conn, tenant_id=tenant_b, role="admin")
    await rls_conn.execute(
        sa.text(
            "INSERT INTO user_permissions (tenant_id, user_id, action, allowed) "
            "VALUES (:t, :u, 'rls-test-action', false)"
        ),
        {"t": tenant_b, "u": user_b},
    )

    await set_app_context(rls_conn, tenant_id=tenant_a, role="admin")
    rows = (await rls_conn.execute(sa.text("SELECT tenant_id FROM user_permissions"))).all()
    assert rows == []
