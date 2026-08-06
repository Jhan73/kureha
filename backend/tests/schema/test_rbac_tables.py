import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from tests.schema.helpers import expect_violation, make_tenant

# A permanently-fictional action key, reserved for this test file's own bare
# (non-`ON CONFLICT`) inserts into the global `action_permissions` catalog.
# MUST NEVER be a real `ACTION_CATALOG` entry (unlike the `appointment:*`/
# `staff:*`/`shift:*`/`session:*`/`calendar:*` namespaces every real action
# key lives under) -- these tests share one real, session-persisting Postgres
# database with `tests/platform/inbound/api/routers`'s router tests, whose
# `client` fixture boots the real app and therefore really commits the real
# `ACTION_CATALOG` via `bootstrap_rbac_catalog_and_grants` (see that
# package's `conftest.py::_cleanup_committed_test_data` docstring). A real
# key here would collide with that seed the moment both run in the same
# pytest session, and would collide again if `ACTION_CATALOG` ever grows a
# `test_probe:*`-shaped entry -- which it structurally never will, since no
# real business resource is named `test_probe`.
_NEVER_SEEDED_ACTION_KEY = "test_probe:never_real"


async def _seed_action(conn, key=_NEVER_SEEDED_ACTION_KEY, *, bulk_cancel_threshold=3) -> None:
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
            "VALUES ('test_probe:never_real', 'bulk cancel')"
        )
    )
    row = (
        await db_conn.execute(
            sa.text(
                "SELECT bulk_cancel_threshold FROM action_permissions WHERE key = 'test_probe:never_real'"
            )
        )
    ).one()
    assert row.bulk_cancel_threshold == 3


async def test_action_permissions_requires_hitl_defaults_false(db_conn) -> None:
    # `test_probe:never_real` (see the module-level `_NEVER_SEEDED_ACTION_KEY`
    # docstring above), not a real `ACTION_CATALOG` key -- deliberately, since
    # this test bare-inserts (no `ON CONFLICT`) into the real, global
    # `action_permissions` table it shares with `tests/platform/inbound/api/
    # routers`'s router tests, whose `client` fixture really commits the real
    # `ACTION_CATALOG` via `app/main.py`'s lifespan in the same pytest
    # session. A real key (this test previously used `appointment:view`)
    # collides with that seed and fails with a duplicate-key error whenever
    # both run in the same session -- confirmed empirically. Unlike a
    # merely-not-yet-seeded real key (e.g. the pre-Phase-11
    # `appointment:cancel_bulk`, which `action_catalog.py` already documents
    # as planned to become real), `test_probe:never_real` is reserved under a
    # resource namespace (`test_probe`) no real business action will ever use
    # -- it cannot collide even after future catalog growth.
    await db_conn.execute(
        sa.text("INSERT INTO action_permissions (key, description) VALUES ('test_probe:never_real', 'bulk cancel')")
    )
    row = (
        await db_conn.execute(
            sa.text("SELECT requires_hitl FROM action_permissions WHERE key = 'test_probe:never_real'")
        )
    ).one()
    assert row.requires_hitl is False


async def test_role_permissions_grant_is_tenant_role_action_scoped(db_conn, tenant_id) -> None:
    await _seed_action(db_conn)
    await db_conn.execute(
        sa.text(
            "INSERT INTO role_permissions (tenant_id, role, action, allowed) "
            "VALUES (:tenant_id, 'reception', 'test_probe:never_real', true)"
        ),
        {"tenant_id": tenant_id},
    )
    row = (
        await db_conn.execute(
            sa.text(
                "SELECT allowed FROM role_permissions "
                "WHERE tenant_id = :tenant_id AND role = 'reception' AND action = 'test_probe:never_real'"
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
            "VALUES (:tenant_id, 'reception', 'test_probe:never_real', true)"
        ),
        {"tenant_id": tenant_id},
    )
    async with expect_violation(db_conn, IntegrityError):
        await db_conn.execute(
            sa.text(
                "INSERT INTO role_permissions (tenant_id, role, action, allowed) "
                "VALUES (:tenant_id, 'reception', 'test_probe:never_real', false)"
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
            "VALUES (:tenant_id, 'reception', 'test_probe:never_real', true)"
        ),
        {"tenant_id": tenant_a},
    )
    await db_conn.execute(
        sa.text(
            "INSERT INTO role_permissions (tenant_id, role, action, allowed) "
            "VALUES (:tenant_id, 'reception', 'test_probe:never_real', false)"
        ),
        {"tenant_id": tenant_b},
    )

    rows = (
        await db_conn.execute(
            sa.text(
                "SELECT tenant_id, allowed FROM role_permissions WHERE action = 'test_probe:never_real' "
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
            "VALUES (:tenant_id, :user_id, 'test_probe:never_real', false)"
        ),
        {"tenant_id": tenant_id, "user_id": user_id},
    )
    row = (
        await db_conn.execute(
            sa.text(
                "SELECT allowed FROM user_permissions "
                "WHERE tenant_id = :tenant_id AND user_id = :user_id AND action = 'test_probe:never_real'"
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
                "VALUES (:tenant_id, :user_id, 'test_probe:never_real', true)"
            ),
            {"tenant_id": tenant_a, "user_id": user_of_b},
        )
