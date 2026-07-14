"""Task 2.5: action_permissions, role_permissions, user_permissions
(design.md §4.4, §5).

`action_permissions` is a global catalog (seeded in code, not tenant-scoped).
`role_permissions`/`user_permissions` are tenant-scoped, keyed by
`(tenant_id, role|user_id, action)`, with `allowed` explicit (deny-by-default
per §5.2: no row for an action means denied, never ambiguous).
"""

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from tests.schema.helpers import expect_violation, make_tenant


async def _seed_action(conn, key="appointment:cancel_bulk", *, bulk_cancel_threshold=3) -> None:
    await conn.execute(
        sa.text(
            "INSERT INTO action_permissions (key, description, bulk_cancel_threshold) "
            "VALUES (:key, 'test action', :threshold)"
        ),
        {"key": key, "threshold": bulk_cancel_threshold},
    )


async def test_action_permissions_default_bulk_cancel_threshold_is_three(db_conn) -> None:
    await db_conn.execute(
        sa.text(
            "INSERT INTO action_permissions (key, description) "
            "VALUES ('appointment:cancel_bulk', 'bulk cancel')"
        )
    )
    row = (
        await db_conn.execute(
            sa.text(
                "SELECT bulk_cancel_threshold FROM action_permissions WHERE key = 'appointment:cancel_bulk'"
            )
        )
    ).one()
    assert row.bulk_cancel_threshold == 3


async def test_action_permissions_requires_hitl_defaults_false(db_conn) -> None:
    await db_conn.execute(
        sa.text("INSERT INTO action_permissions (key, description) VALUES ('appointment:view', 'view')")
    )
    row = (
        await db_conn.execute(
            sa.text("SELECT requires_hitl FROM action_permissions WHERE key = 'appointment:view'")
        )
    ).one()
    assert row.requires_hitl is False


async def test_role_permissions_grant_is_tenant_role_action_scoped(db_conn, tenant_id) -> None:
    await _seed_action(db_conn)
    await db_conn.execute(
        sa.text(
            "INSERT INTO role_permissions (tenant_id, role, action, allowed) "
            "VALUES (:tenant_id, 'reception', 'appointment:cancel_bulk', true)"
        ),
        {"tenant_id": tenant_id},
    )
    row = (
        await db_conn.execute(
            sa.text(
                "SELECT allowed FROM role_permissions "
                "WHERE tenant_id = :tenant_id AND role = 'reception' AND action = 'appointment:cancel_bulk'"
            ),
            {"tenant_id": tenant_id},
        )
    ).one()
    assert row.allowed is True


async def test_role_permissions_rejects_action_not_in_catalog(db_conn, tenant_id) -> None:
    async with expect_violation(db_conn):
        await db_conn.execute(
            sa.text(
                "INSERT INTO role_permissions (tenant_id, role, action, allowed) "
                "VALUES (:tenant_id, 'reception', 'nonexistent:action', true)"
            ),
            {"tenant_id": tenant_id},
        )


async def test_role_permissions_same_tenant_role_action_is_unique(db_conn, tenant_id) -> None:
    await _seed_action(db_conn)
    await db_conn.execute(
        sa.text(
            "INSERT INTO role_permissions (tenant_id, role, action, allowed) "
            "VALUES (:tenant_id, 'reception', 'appointment:cancel_bulk', true)"
        ),
        {"tenant_id": tenant_id},
    )
    async with expect_violation(db_conn, IntegrityError):
        await db_conn.execute(
            sa.text(
                "INSERT INTO role_permissions (tenant_id, role, action, allowed) "
                "VALUES (:tenant_id, 'reception', 'appointment:cancel_bulk', false)"
            ),
            {"tenant_id": tenant_id},
        )


async def test_role_permissions_may_repeat_action_across_tenants(db_conn) -> None:
    await _seed_action(db_conn)
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)

    await db_conn.execute(
        sa.text(
            "INSERT INTO role_permissions (tenant_id, role, action, allowed) "
            "VALUES (:tenant_id, 'reception', 'appointment:cancel_bulk', true)"
        ),
        {"tenant_id": tenant_a},
    )
    await db_conn.execute(
        sa.text(
            "INSERT INTO role_permissions (tenant_id, role, action, allowed) "
            "VALUES (:tenant_id, 'reception', 'appointment:cancel_bulk', false)"
        ),
        {"tenant_id": tenant_b},
    )

    rows = (
        await db_conn.execute(
            sa.text(
                "SELECT tenant_id, allowed FROM role_permissions WHERE action = 'appointment:cancel_bulk' "
                "ORDER BY allowed"
            )
        )
    ).all()
    assert len(rows) == 2


async def test_user_permissions_override_is_tenant_user_action_scoped(db_conn, tenant_id) -> None:
    from tests.schema.helpers import make_site, make_user

    await _seed_action(db_conn)
    site_id = await make_site(db_conn, tenant_id)
    user_id = await make_user(db_conn, tenant_id, site_id, role="reception")

    await db_conn.execute(
        sa.text(
            "INSERT INTO user_permissions (tenant_id, user_id, action, allowed) "
            "VALUES (:tenant_id, :user_id, 'appointment:cancel_bulk', false)"
        ),
        {"tenant_id": tenant_id, "user_id": user_id},
    )
    row = (
        await db_conn.execute(
            sa.text(
                "SELECT allowed FROM user_permissions "
                "WHERE tenant_id = :tenant_id AND user_id = :user_id AND action = 'appointment:cancel_bulk'"
            ),
            {"tenant_id": tenant_id, "user_id": user_id},
        )
    ).one()
    assert row.allowed is False


async def test_user_permissions_rejects_action_not_in_catalog(db_conn, tenant_id) -> None:
    from tests.schema.helpers import make_site, make_user

    site_id = await make_site(db_conn, tenant_id)
    user_id = await make_user(db_conn, tenant_id, site_id, role="reception")

    async with expect_violation(db_conn):
        await db_conn.execute(
            sa.text(
                "INSERT INTO user_permissions (tenant_id, user_id, action, allowed) "
                "VALUES (:tenant_id, :user_id, 'nonexistent:action', true)"
            ),
            {"tenant_id": tenant_id, "user_id": user_id},
        )


async def test_user_permissions_user_id_must_belong_to_same_tenant(db_conn) -> None:
    """Composite FK (tenant_id, user_id) -> users(tenant_id, id): a user from
    a different tenant must not be assignable an override in this tenant."""
    from tests.schema.helpers import make_site, make_user

    await _seed_action(db_conn)
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    site_b = await make_site(db_conn, tenant_b)
    user_of_b = await make_user(db_conn, tenant_b, site_b, role="reception")

    async with expect_violation(db_conn):
        await db_conn.execute(
            sa.text(
                "INSERT INTO user_permissions (tenant_id, user_id, action, allowed) "
                "VALUES (:tenant_id, :user_id, 'appointment:cancel_bulk', true)"
            ),
            {"tenant_id": tenant_a, "user_id": user_of_b},
        )
